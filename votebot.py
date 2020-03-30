from enum import Enum
from itertools import groupby
from bot import *
import logging
from dialog_api import peers_pb2, users_pb2, messaging_pb2, search_pb2, sequence_and_updates_pb2, groups_pb2
from dialog_bot_sdk.entities.media.InteractiveMediaGroup import InteractiveMediaStyle
from dialog_bot_sdk.interactive_media import InteractiveMediaGroup, InteractiveMedia, InteractiveMediaSelect, \
    InteractiveMediaConfirm, InteractiveMediaButton
from dialog_bot_sdk.entities.UUID import UUID
from pymongo import MongoClient
from config import *

logger = logging.getLogger('votebot')
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

class PollStates(Enum):
    ELSE = '-1'
    START = '0'
    ENTER_TITLE = '1'
    ENTER_OPTION = '2'
    ENTER_SHOW_OPTION = '3'
    
class DBNames(Enum):
    STATES = 'states'
    LAST_POLL_ID = 'last_poll_id'
    TITLES = 'titles'
    OPTIONS = 'options'
    POLLS = 'polls'  


class PollStrategy(Strategy):
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = MongoClient(MONGODBLINK)
        self.db = self.client[DBNAME]
                
    def get_value(self, uid, table):
        val = self.db[table].find_one({'_id': uid})
        if val is None:
            if table in [DBNames.STATES.value, DBNames.LAST_POLL_ID.value]:
                return PollStates.START.value
            else:
                return ''
        return val['value']
        
    def reset_state(self, uid):
        poll_id = self.get_value(uid, DBNames.LAST_POLL_ID.value)
        self.increment_value(uid, poll_id, DBNames.LAST_POLL_ID.value)
        return self.set_value(uid, PollStates.START.value, DBNames.STATES.value)
    
    def increment_value(self, uid, value, table):
        self.set_value(uid, str(int(value) + 1), table)
                
    def set_value(self, uid, value, table):
        self.db[table].replace_one({'_id': uid}, {'value': value}, upsert=True)
        return value
                
    def add_value(self, value, table, uid):
        val = self.db[table].find_one({'_id': uid})
        if val is None:
            self.db[table].insert_one({'_id': uid, 'value': [value]}) 
        else:
            self.db[table].update({'_id': uid}, {'$push': {'value': value}})     
            
    def get_dict_from_db(self, table):
        cursor = self.db[table].find({})
        return {x['_id']: x['value'] for x in cursor}
        
    def get_set_from_db(self, table, uid):
        return set(self.get_value(uid, table))      
            
    def get_answers(self, poll_id):
        answers = self.get_dict_from_db('answers_'+poll_id)
        res = {key: 100*len(list(group))//len(answers) for key, group in groupby(answers.values())}
        users = {option:[key for (key, value) in answers.items() if value == option] for option in res.keys()}
        return (users, res)
    
    
    def update_res(self, poll_id, close=False):
        (users, res) = self.get_answers(poll_id)
        table = DBNames.POLLS.value
        self.update_poll(self.get_set_from_db(table, 'mids_'+poll_id), poll_id, res, close=close, users=users)
        self.update_poll(self.get_set_from_db(table, 'creator_mids_'+poll_id), 
                             poll_id, res, creator=True, close=close, users=users)
            
    def send_buttons(self, peer, title, options):
        return self.bot.messaging.send_message(
            peer, title,
            [InteractiveMediaGroup(
                [InteractiveMedia(
                    option[0],
                    InteractiveMediaButton(
                        *option)
                        )
                for option in options]
            )]
        ).wait()
    
    def update_buttons(self, msg, title, options=None):
        if not options:
            return self.bot.messaging.update_message(
            msg, title) 
        else:    
            return self.bot.messaging.update_message(
                msg, title,
                [InteractiveMediaGroup(
                    [InteractiveMedia(
                        option[0],
                        InteractiveMediaButton(
                            *option)
                            )
                    for option in options]
                )]
            ) 
        
    def get_nicks_from_ids(self, uids):
        uids = [int(uid) for uid in uids]
        req = messaging_pb2.RequestLoadDialogs(
            min_date=0,
            limit=100,
            peers_to_load=[peers_pb2.Peer(type=peers_pb2.PEERTYPE_PRIVATE, id=uid) 
                          for uid in uids]
        )
        result = self.bot.internal.messaging.LoadDialogs(req)
        users_list = self.bot.internal.updates.GetReferencedEntitites(
            sequence_and_updates_pb2.RequestGetReferencedEntitites(
                users=list(result.user_peers)
            )
        )
        return [user.data.nick.value for user in users_list.users if user.id in uids]
    
    def get_users_for_option(self, users, option):
        users = ', '.join(['@' + nick for nick in 
                                        self.get_nicks_from_ids(users[option][:5])])
        if users != '':
            users = ' \n ' + users
        return users
        
    
    def _make_poll_params(self, title, options, vote_perc, creator, poll_id, close=False, users={}):
        for option in options - vote_perc.keys():
            vote_perc[option] = 0
            users[option] = []
        res = [(option,  " - " + str(option) + " - " + str(vote_perc[option]) + "%") for option in options]
        options = [('answer_'+ option + '_' + poll_id, str(option)) for option in options] 
        show = self.get_value('show_' + poll_id, DBNames.POLLS.value)
        if show == 'show':
            res = [ (x, y + self.get_users_for_option(users, x)) for(x,  y) in res]
        title +=' \n \n ' + ' \n \n '.join([y for (x, y) in res]) + ' \n \n Голосов: {}'.format(sum([len(x) for x in users.values()])) 
        if close or creator:
            if not creator:
                return {'title': title}
            elif not close:
                options = [(x + '_' + poll_id, y) for (x, y) in [('update', 'Обновить результаты'),
                            ('publish', 'Скопировать'), ('close', 'Закрыть')]]   
            else:
                options = [(x + '_' + poll_id, y) for (x, y) in [('update', 'Обновить результаты'),
                            ('publish', 'Скопировать'), ('open', 'Открыть')]]    
        
        return {'title': title, 'options': options}
    
    def send_poll(self, peer, title, options, poll_id, vote_perc={}, creator=False,):
        try:
            (users, answers) = self.get_answers(poll_id)
        except:
            (users, answers) = ({}, {})
        params = self._make_poll_params(title, options, answers, creator, poll_id, close=False, users=users)
        self.save_mids(self.send_buttons(peer=peer, **params), poll_id, creator)
            
    def update_poll(self, mids, poll_id,  vote_perc={}, creator=False, close=False, users={}):
        uuids = [UUID(*[int(x) for x in mid.split('_')]) for mid in mids][::-1]
        msgs = self.bot.messaging.get_messages_by_id(uuids).wait()
        title = self.get_value(poll_id, DBNames.TITLES.value)
        options = self.get_value(poll_id, DBNames.OPTIONS.value).split(' \n ')
        params = self._make_poll_params(title, options, vote_perc, creator, poll_id, close, users)
        for msg in msgs:
            self.update_buttons(msg=msg, **params)
    
    def get_user_bot_groups(self, uid):
        request = search_pb2.RequestPeerSearch(
            query=[
                search_pb2.SearchCondition(
                    searchPeerTypeCondition=search_pb2.SearchPeerTypeCondition(
                        peer_type=search_pb2.SEARCHPEERTYPE_GROUPS
                    )
                ),
                search_pb2.SearchCondition(
                    searchPieceText=search_pb2.SearchPieceText(query='')
                )
            ]
        )
        response = self.bot.internal.search.PeerSearch(request).search_results
        return response
    
    def save_mids(self, uuid, poll_id, creator=False):
        uuid = {"msb": uuid.msb, "lsb": uuid.lsb}
        mid = str(uuid['msb']) + '_' + str(uuid['lsb'])
        table = DBNames.POLLS.value
        if creator:
            self.add_value(mid, table, 'creator_mids_'+str(poll_id))
        else:
            self.add_value(mid, table, 'mids_'+str(poll_id))
            
    def _handle_start(self, peer):
        uid = peer.id
        state = self.reset_state(uid)
        name = self.bot.users.get_user_by_id(uid).wait().data.name
        self.bot.messaging.send_message(peer, config[PollStates(state).name].format(name))
        self.increment_value(uid, state, DBNames.STATES.value) 
        
    def _handle_enter_title(self, peer, poll_id, title):
        state = PollStates.ENTER_TITLE.value
        self.set_value(poll_id, title, DBNames.TITLES.value)
        self.bot.messaging.send_message(peer, config[PollStates(state).name])
        self.increment_value(peer.id, state, DBNames.STATES.value)  
        
    def _handle_enter_option(self, peer, poll_id, text):
        state = PollStates.ENTER_OPTION.value
        uid = peer.id
        if text == '/stop':
            self.increment_value(uid, state, DBNames.STATES.value)   
            params = config[PollStates(self.get_value(uid, DBNames.STATES.value)).name]
            button_params = {'title': params['title'], 'options': [(x + '_' + poll_id, y) for (x, y) in params['options']]}
            self.send_buttons(peer, **button_params)
        else:
            options = self.get_value(poll_id, DBNames.OPTIONS.value)
            if options != '':
                text = options + ' \n ' + text
            self.set_value(poll_id, text, DBNames.OPTIONS.value)
            self.bot.messaging.send_message(peer, config[PollStates(state).name])  
        
    
    def on_msg(self, params):
            peer = params.peer
            if peer.id != params.sender_peer.id:
                return
            text = params.message.text_message.text
            uid = peer.id
            state = self.get_value(uid, DBNames.STATES.value)
            poll_id = str(uid) + 'p' + self.get_value(uid, DBNames.LAST_POLL_ID.value)

            if text == u'/start':
                self._handle_start(peer)
                
            elif state == PollStates.ENTER_TITLE.value:
                self._handle_enter_title(peer, poll_id, text) 
                
            elif state == PollStates.ENTER_OPTION.value:
                self._handle_enter_option(peer, poll_id, text)
            else:
                self.bot.messaging.send_message(peer, config[PollStates.ELSE.name])
     
                
    def _handle_publish_option(self, peer, value, uid):
        params = value.split('_', 1)
        poll_id = params[1]
        if params[0] != 'publish':
            self.set_value(uid, PollStates.START.value,  DBNames.STATES.value)
            self.set_value('show_' + poll_id, params[0], DBNames.POLLS.value)
        if 'publish' in value:
            self.update_res(poll_id, close=False)
        groups = [x for x in self.get_user_bot_groups(uid) if x.is_joined.value]
        self.bot.messaging.send_message(peer, 'Куда отправляем', [
                InteractiveMediaGroup(
                    [
                        InteractiveMedia(
                            "select_id",
                            InteractiveMediaSelect({'group_' + str(gr.peer.id) + '_' + str(poll_id) : gr.title for gr in groups}, "Выберите группу", "choose"),
                            InteractiveMediaStyle.INTERACTIVEMEDIASTYLE_DANGER,
                        )
                    ]
                )
            ])


    def _handle_send(self, peer, value, uid):
        params = value.split('_')
        group_id = int(params[1])
        poll_id = params[2]
        group = self.bot.groups.find_group_by_id(group_id).wait()
        title = self.get_value(poll_id, DBNames.TITLES.value)
        options = self.get_value(poll_id, DBNames.OPTIONS.value)
        self.send_poll(group.peer, title, options.split(' \n '), poll_id)
        self.send_poll(peer,
                        'Готово, опрос опубликован в группу {}. \n \n {}'.format(group.data.title, title), options.split(' \n '), creator=True, poll_id=poll_id)


    def _handle_new_answer(self, peer, value, uid):
        params = value.split('_')
        poll_id = params[2]
        answer = params[1]
        self.set_value(uid, answer, 'answers_' + poll_id)
        self.update_res(poll_id)
    
    def on_click(self, params):
        peer = params.peer
        value = params.value
        uid = peer.id
        if 'publish_' in value or (('anon_' in value or 'show_' in value) 
            and self.get_value(uid, DBNames.STATES.value) == PollStates.ENTER_SHOW_OPTION.value):
            self._handle_publish_option(peer, value, uid)
        elif 'group_' in value:
            self._handle_send(peer, value, uid)
        elif 'answer_' in value:
            self._handle_new_answer(peer, value, uid)
        elif 'update_' in value:
            self.update_res(value.split('_')[1])
        elif 'close_' in value:
            poll_id = value.split('_')[1]
            self.update_res(poll_id, close=True)
        elif 'open_' in value:
            poll_id = value.split('_')[1]
            self.update_res(poll_id, close=False)
        else:
            pass
            
            

if __name__ == '__main__':
    while True:
        try:
            logger.info('Start')
            strategy = PollStrategy(token=BOT_TOKEN,
                                           endpoint=BOT_ENDPOINT,async_=False)
            strategy.start()
        except Exception as e:
            logger.exception(e)
            continue

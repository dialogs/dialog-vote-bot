BOT_TOKEN = '241e86e8c21646c194bf556e7c7e50642ed408cc'
BOT_ENDPOINT = 'demo-eem.transmit.im'
DBNAME = 'votebot'
MONGODBLINK = 'mongodb://localhost:27017/'
LOGS_FILE = 'votebot.logs'

config = {'ELSE' : 'Я вас не понимаю. Вот список доступных команд: \n /start - создать новый опрос',
          'START': 
          '{}, добрый день! \n ⁣Давайте создадим опрос. Напишите ваш вопрос, на который будет создано голосование',
          'ENTER_TITLE': 'Понял. Теперь напишите первый вариант ответа',
          'ENTER_OPTION': 'Ок. Теперь напишите новый вариант ответа или /stop, чтобы остановить',
          'ENTER_SHOW_OPTION': {'title': 'Показывать, кто и как проголосовал?', 'options': [('anon', 'Анонимно'), ('show', 'Показывать')]}
    
}

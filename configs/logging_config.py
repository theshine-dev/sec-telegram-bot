# log_setup.py
import os
import logging.config

from dotenv import load_dotenv

from configs.config import LOG_DIR

load_dotenv(dotenv_path='../.env')
GLOBAL_LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,  # 기존 라이브러리 로거 비활성화 방지

    # 로그 포맷 정의
    'formatters': {
        'default': {
            'format': '%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'simple': {
            'format': '%(asctime)s - %(levelname)s - %(message)s',
        },
    },

    # 핸들러(출력 방식) 정의: 어디로 보낼 것인가?
    'handlers': {
        # 콘솔(터미널) 출력용
        'console': {
            'level': GLOBAL_LOG_LEVEL,
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'stream': 'ext://sys.stdout',  # Docker에서 잘 보이도록 stdout 사용
        },
        # 봇 메인 로직 및 일반용
        'bot_file_handler': {
            'level': GLOBAL_LOG_LEVEL,
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'bot.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5,
            'formatter': 'default',
            'encoding': 'utf-8',
        },
        # DB 관련 로직용
        'db_file_handler': {
            'level': GLOBAL_LOG_LEVEL,
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'database.log',
            'maxBytes': 5242880,  # 5MB
            'backupCount': 3,
            'formatter': 'default',
            'encoding': 'utf-8',
        },
        # SEC API 및 티커 검증 로직용
        'sec_file_handler': {
            'level': GLOBAL_LOG_LEVEL,
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'sec_api.log',
            'maxBytes': 5242880,  # 5MB
            'backupCount': 3,
            'formatter': 'default',
            'encoding': 'utf-8',
        },
        'background_file_handler': {
            'level': GLOBAL_LOG_LEVEL,
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'background_process.log',
            'maxBytes': 5242880,  # 5MB
            'backupCount': 3,
            'formatter': 'default',
            'encoding': 'utf-8',
        },
        'gemini_file_handler': {
            'level': GLOBAL_LOG_LEVEL,
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'gemini_request.log',
            'maxBytes': 5242880,  # 5MB
            'backupCount': 3,
            'formatter': 'default',
            'encoding': 'utf-8',
        },
    },

    # 로거(Logger) 정의: 누가, 어떤 핸들러를 사용할 것인가?
    'loggers': {
        # __name__이 'db_manager'인 경우
        'modules.db_manager': {
            'level': GLOBAL_LOG_LEVEL,
            'handlers': ['console', 'db_file_handler'],
            'propagate': False,  # 부모(root)로 로그 전파 차단
        },
        # __name__이 'sec_helper' 또는 'ticker_validator'인 경우
        'modules.sec_helper': {
            'level': GLOBAL_LOG_LEVEL,
            'handlers': ['console', 'sec_file_handler'],
            'propagate': False,
        },
        'modules.ticker_validator': {
            'level': GLOBAL_LOG_LEVEL,
            'handlers': ['console', 'sec_file_handler'],
            'propagate': False,
        },
        'modules.bg_task': {
            'level': GLOBAL_LOG_LEVEL,
            'handlers': ['console', 'background_file_handler'],
            'propagate': False,
        },
        'modules.gemini_helper': {
            'level': GLOBAL_LOG_LEVEL,
            'handlers': ['console', 'gemini_file_handler'],
            'propagate': False,
        },
        'main': {
            'level': GLOBAL_LOG_LEVEL,
            'handlers': ['console', 'bot_file_handler'],
            'propagate': False,
        },
        # apscheduler, httpx, httpcore가 너무 시끄럽지 않도록 레벨 조정
        'apscheduler': {
            'level': 'WARNING',
            'handlers': ['console', 'bot_file_handler'],
            'propagate': False,
        },
        'httpx': {
            'level': 'WARNING',
            'handlers': ['console', 'bot_file_handler'],
            'propagate': False,
        },
        'httpcore': {
            'level': 'WARNING',
            'handlers': ['console', 'bot_file_handler'],
            'propagate': False,
        },
    },

    # 위에 명시되지 않은 모든 로거(라이브러리 등)의 기본 설정
    'root': {
        'level': GLOBAL_LOG_LEVEL,
        'handlers': ['console', 'bot_file_handler'],
    }
}

def setup_logging():
    """
    configs.py의 LOGGING_CONFIG 딕셔너리를 기반으로
    로깅 시스템을 설정하고 폴더를 생성합니다.
    """
    # 로그 디렉토리 생성
    os.makedirs(LOG_DIR, exist_ok=True)

    # 딕셔너리 설정 적용
    logging.config.dictConfig(LOGGING_CONFIG)
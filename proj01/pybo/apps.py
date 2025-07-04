from django.apps import AppConfig #type: ignore


class PyboConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pybo'

    def ready(self):
        # 앱이 준비될 때 signals 모듈을 import
        import pybo.signals    
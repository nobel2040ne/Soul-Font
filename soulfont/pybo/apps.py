from django.apps import AppConfig #type: ignore


class PyboConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pybo'

    def ready(self):
        import pybo.signals    
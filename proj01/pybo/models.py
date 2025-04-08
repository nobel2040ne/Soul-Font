from django.db import models

class Font(models.Model):
    text = models.CharField(max_length=255, default="No Description")
    font_description = models.TextField(null=True, blank=True)
    ttf_file = models.FileField(upload_to='fonts/')

    def __str__(self):
        return self.text
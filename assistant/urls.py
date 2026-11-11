from django.urls import path

from assistant import views

app_name = "assistant"

urlpatterns = [
    path("chat/", views.chat, name="chat"),
    path("history/", views.history, name="history"),
    path("reset/", views.reset, name="reset"),
]

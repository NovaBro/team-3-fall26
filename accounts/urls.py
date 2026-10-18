from django.contrib.auth.views import LoginView
from django.urls import path

from accounts import views

app_name = "accounts"


class ProfileLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


urlpatterns = [
    path("profile/", views.profile, name="profile"),
    path("signup/", views.signup, name="signup"),
    path("login/", ProfileLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
]

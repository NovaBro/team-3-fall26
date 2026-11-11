from django.contrib.auth.views import LoginView
from django.urls import path

from accounts import views
from accounts.forms import LoginForm

app_name = "accounts"


class ProfileLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True
    authentication_form = LoginForm


urlpatterns = [
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path(
        "admin-dashboard/users/<int:user_id>/",
        views.admin_user_detail,
        name="admin_user_detail",
    ),
    path("profile/", views.profile, name="profile"),
    path("profile/<str:username>/", views.view_profile, name="view_profile"),
    path("signup/", views.signup, name="signup"),
    path("login/", ProfileLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("verify/<str:uidb64>/<str:token>/", views.verify_email, name="verify_email"),
]

from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = "synopsis"

urlpatterns = [
    # Simple shortcut for login
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    # very basic for now dashboard and hub
    path("", views.dashboard, name="dashboard"),
    path("project/<int:project_id>/", views.project_hub, name="project_hub"),
    path(
        "project/<int:project_id>/protocol/",
        views.protocol_detail,
        name="protocol_detail",
    ),
    path("project/<int:project_id>/team/", views.team_manage, name="team_manage"),
]

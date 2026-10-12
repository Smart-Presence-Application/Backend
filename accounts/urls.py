"""Account URL routes."""
from django.urls import path

from accounts.views import LoginView, LogoutView, RefreshView, ProfileView, ProfileImageView, ChangePasswordView, SingleUserStatusView, BulkUserStatusView, UserView

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("refresh/", RefreshView.as_view(), name="refresh"),
    
    path("profile/", ProfileView.as_view(), name="me"),
    path("profile/image/", ProfileImageView.as_view(), name="profile-image-update"),
    path("profile/change-password/", ChangePasswordView.as_view(), name="change-password"),
    
    path("users/", UserView.as_view(), name="user-list"),
    path("users/<int:user_id>/", UserView.as_view(), name="user-detail"),
    path("users/<int:user_id>/change-password/", ChangePasswordView.as_view(), name="admin-change-password"),
    path("users/<int:user_id>/status/", SingleUserStatusView.as_view(), name="admin-user-status"),
    path("users/bulk-status/", BulkUserStatusView.as_view(), name="admin-bulk-user-status"),
]

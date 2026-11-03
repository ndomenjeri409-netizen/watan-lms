from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models

from common.models import BaseModel

from .roles import Role


class UserManager(BaseUserManager):
    def create_user(self, firebase_uid, email="", **extra):
        user = self.model(firebase_uid=firebase_uid, email=email, **extra)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, firebase_uid, password=None, **extra):
        if not password:
            raise ValueError("A password is required for a superuser.")
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", Role.SUPER_ADMIN)
        user = self.model(firebase_uid=firebase_uid, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    firebase_uid = models.CharField(max_length=128, unique=True)
    email = models.EmailField(blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    USERNAME_FIELD = "firebase_uid"
    objects = UserManager()

    def __str__(self):
        return self.email or self.firebase_uid

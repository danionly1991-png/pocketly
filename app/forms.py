"""Flask-WTF forms for the auth pages. Error messages come from spec 02, section 7."""

import re

from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, ValidationError

NAME_MESSAGE = "Please enter your name (2–50 characters)."
EMAIL_MESSAGE = "Please enter a valid email."
PASSWORD_MESSAGE = "Password must be at least 8 characters and include a letter and a number."
CONFIRM_MESSAGE = "Passwords don't match."


def _strip(value):
    return value.strip() if isinstance(value, str) else value


def _clean_email(value):
    return value.strip().lower() if isinstance(value, str) else value


def password_rule(_form, field):
    value = field.data or ""
    if len(value) < 8 or not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValidationError(PASSWORD_MESSAGE)


def _email_field(optional: bool = False):
    # No DNS lookups (check_deliverability=False): faster, and fine on serverless.
    first = Optional() if optional else DataRequired(message=EMAIL_MESSAGE)
    return StringField(
        "Email",
        filters=[_clean_email],
        validators=[first, Email(message=EMAIL_MESSAGE, check_deliverability=False)],
    )


class SignupForm(FlaskForm):
    name = StringField(
        "Name",
        filters=[_strip],
        validators=[DataRequired(message=NAME_MESSAGE), Length(min=2, max=50, message=NAME_MESSAGE)],
    )
    email = _email_field()
    password = PasswordField("Password", validators=[DataRequired(message=PASSWORD_MESSAGE), password_rule])
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(message=CONFIRM_MESSAGE), EqualTo("password", message=CONFIRM_MESSAGE)],
    )


class LoginForm(FlaskForm):
    email = _email_field()
    # Only checks the field isn't empty, so we don't hint at the password rules.
    password = PasswordField("Password", validators=[DataRequired(message="Please enter your password.")])


class ForgotPasswordForm(FlaskForm):
    email = _email_field()


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New password", validators=[DataRequired(message=PASSWORD_MESSAGE), password_rule])
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(message=CONFIRM_MESSAGE), EqualTo("password", message=CONFIRM_MESSAGE)],
    )


class ResendForm(FlaskForm):
    """Resend the verification email. The email is optional: we fall back to the one from sign-up."""

    email = _email_field(optional=True)

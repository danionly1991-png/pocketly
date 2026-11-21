"""Flask-WTF forms. Auth messages come from spec 02 section 7, expense/category ones from spec 03 section 8."""

import re
from decimal import Decimal, InvalidOperation

from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import HiddenField, PasswordField, RadioField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, ValidationError

from app.services.storage import ICON_MESSAGE, IconError, process_icon
from app.utils.dates import karachi_today, parse_iso_date

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


# --- Spec 03: expenses and categories ----------------------------------------

AMOUNT_MESSAGE = "Enter an amount greater than 0."
CATEGORY_MESSAGE = "Please choose a category."
DATE_MESSAGE = "Please choose a valid date."
FUTURE_DATE_MESSAGE = "Date can't be in the future."
NOTE_MESSAGE = "Note can be up to 500 characters."
CATEGORY_NAME_MESSAGE = "Category name must be 1–30 characters."
EMOJI_MESSAGE = "Please choose an emoji."
MAX_AMOUNT = Decimal("9999999.99")

# 30 presets (food, transport, bills, health, gifts, ...). Includes all 7 default icons.
PRESET_EMOJIS = [
    "🍔", "🍕", "☕", "🍩", "🛒", "🚌", "🚕", "⛽", "✈️", "📱",
    "💡", "💧", "🏠", "🧾", "💊", "🏥", "🎁", "🎉", "🛍️", "👕",
    "📚", "✏️", "🎓", "🎬", "🎮", "🎵", "⚽", "💇", "🐾", "📦",
]


def _none_if_empty(value):
    return value or None


class ExpenseForm(FlaskForm):
    amount = StringField("Amount", filters=[_strip])
    category_id = StringField("Category", filters=[_strip])
    spent_on = StringField("Date", filters=[_strip])
    note = TextAreaField(
        "Note",
        filters=[_strip, _none_if_empty],
        validators=[Optional(), Length(max=500, message=NOTE_MESSAGE)],
    )
    # Which dashboard view the user was on, so we can send them back to it.
    return_month = HiddenField()
    return_day = HiddenField()

    # Set by the route before validating / by the validators.
    allowed_category_ids: frozenset = frozenset()
    amount_value: Decimal | None = None
    spent_on_value = None

    def validate_amount(self, field):
        raw = (field.data or "").replace(",", "").strip()
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise ValidationError(AMOUNT_MESSAGE) from None
        if not value.is_finite() or value <= 0 or value > MAX_AMOUNT or value.as_tuple().exponent < -2:
            raise ValidationError(AMOUNT_MESSAGE)
        self.amount_value = value

    def validate_category_id(self, field):
        if (field.data or "") not in self.allowed_category_ids:
            raise ValidationError(CATEGORY_MESSAGE)

    def validate_spent_on(self, field):
        value = parse_iso_date(field.data)
        if value is None:
            raise ValidationError(DATE_MESSAGE)
        if value > karachi_today():
            raise ValidationError(FUTURE_DATE_MESSAGE)
        self.spent_on_value = value


class CategoryForm(FlaskForm):
    name = StringField(
        "Name",
        filters=[_strip],
        validators=[DataRequired(message=CATEGORY_NAME_MESSAGE), Length(min=1, max=30, message=CATEGORY_NAME_MESSAGE)],
    )
    icon_type = RadioField("Icon", choices=[("emoji", "Emoji"), ("image", "Upload photo")], default="emoji")
    emoji = StringField("Emoji")  # rendered by hand as a grid of radio buttons
    photo = FileField("Photo")

    # Set by the route (editing a category that already has a photo) / by validate_photo.
    has_existing_image: bool = False
    icon_bytes: bytes | None = None

    def validate_emoji(self, field):
        if self.icon_type.data == "emoji" and field.data not in PRESET_EMOJIS:
            raise ValidationError(EMOJI_MESSAGE)

    def validate_photo(self, field):
        if self.icon_type.data != "image":
            return
        upload = field.data
        if upload is not None and getattr(upload, "filename", ""):
            try:
                self.icon_bytes = process_icon(upload)
            except IconError:
                raise ValidationError(ICON_MESSAGE) from None
        elif not self.has_existing_image:
            raise ValidationError(ICON_MESSAGE)

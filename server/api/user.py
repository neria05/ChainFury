import database
from typing import Annotated
from database import User
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Query, Header
from pydantic import BaseModel
from commons.utils import get_user_from_jwt, verify_user

user_router = APIRouter(prefix="/user", tags=["user"])


class ChangePasswordModel(BaseModel):
    username: str
    old_password: str
    new_password: str


@user_router.post("/change_password", status_code=200)
def change_password(inputs: ChangePasswordModel, token: Annotated[str, Header()], db: Session = Depends(database.db_session)):
    user = get_user_from_jwt(token)
    verify_user(user)
    user: User = db.query(User).filter((User.username == inputs.username) & (User.password == inputs.old_password)).first()
    if user is not None:
        user.password = inputs.new_password
        db.commit()
        response = {"msg": "success"}
    else:
        response = {"msg": "failed"}
    return response

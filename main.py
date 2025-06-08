import uvicorn

import secrets
import hashlib
from typing import ClassVar
from contextlib import asynccontextmanager

from fastapi import FastAPI, status, Request, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse

from sqlmodel import Field, Session, SQLModel, create_engine, select


# setup the goods class
class Goods(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    amount: int | None = Field(default=1, index=True)
    price: float | None = Field(default=None, index=True)


# setup the global data class
class GlobalData(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True)
    value: str


# setup the database
sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {
    "check_same_thread": False
}  # many threads can access the database at the same time
engine = create_engine(sqlite_url, connect_args=connect_args)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


# create the database when the app starts
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


# create the app
app = FastAPI(lifespan=lifespan)


# Welcome message
@app.get("/", response_class=PlainTextResponse)
async def root():
    return "Welcome to my simple web server"


# Digest authenticate
# dictionary of users and passwords
USERS = {"tinikov": "SU(3)group"}


# trim the string
def trim_str(str):
    str = str.replace(",", "")
    return eval(str)


# calculate response
def calculate_md5(data):
    return hashlib.md5(data.encode()).hexdigest()


def calculate_ha1(username, realm, password):
    return calculate_md5(f"{username}:{realm}:{password}")


def calculate_ha2(method, uri):
    return calculate_md5(f"{method}:{uri}")


def calculate_response(ha1, nonce, ha2):
    return calculate_md5(f"{ha1}:{nonce}:{ha2}")


@app.get("/secret", response_class=PlainTextResponse)
async def auth(request: Request):
    # set the realm
    realm = "tinikov-webserver"

    # get the authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header:
        method = request.method
        uri = request.url.path
        username = ""
        returned_nonce = ""
        returned_response = ""
        for i in auth_header.split(" "):
            if i.startswith("username="):
                username = trim_str(i.split("=")[1])
            if i.startswith("nonce="):
                returned_nonce = trim_str(i.split("=")[1])
            if i.startswith("response="):
                returned_response = trim_str(i.split("=")[1])

        # check the username and password
        if username in USERS:
            password = USERS[username]
            ha1 = calculate_ha1(username, realm, password)
            ha2 = calculate_ha2(method, uri)
            expected_response = calculate_response(ha1, returned_nonce, ha2)

            if returned_response == expected_response:
                return "SUCCESS"

    # generate a random nonce
    nonce = secrets.token_hex(16)
    # set the www-authenticate header
    headers = {"WWW-Authenticate": f'Digest realm="{realm}",nonce="{nonce}"'}

    raise HTTPException(
        status_code=401,
        headers=headers,
        detail="Unauthorized",
    )


# Sales system
# Supp functions
def raise_error():
    return JSONResponse(
        content={"message": "ERROR"},
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def check_good_keys(good: dict):
    valid_keys = ["name", "amount"]
    for key in good.keys():
        if key not in valid_keys:
            return False
    if not good.get("name"):
        return False
    if good.get("amount"):
        if not isinstance(good["amount"], int) or good["amount"] <= 0:
            return False
    return True


def check_sale_keys(sale: dict):
    valid_keys = ["name", "amount", "price"]
    for key in sale.keys():
        if key not in valid_keys:
            return False
    if not sale.get("name"):
        return False
    if sale.get("amount"):
        if not isinstance(sale["amount"], int):
            return False
        if sale["amount"] <= 0:
            return False
    if sale.get("price"):
        if not isinstance(sale["price"], (int, float)):
            return False
        if sale["price"] <= 0.0:
            return False
    return True


def update_total_sales(session: Session, amount_to_add: float):
    # find total sales
    sales_query = select(GlobalData).where(GlobalData.key == "total_sales")
    sales = session.exec(sales_query).one_or_none()

    if sales:
        # update
        current_total = float(sales.value)
        new_total = current_total + amount_to_add
        sales.value = str(new_total)
    else:
        # create
        sales = GlobalData(key="total_sales", value=str(amount_to_add))
        session.add(sales)


def get_total_sales() -> float:
    with Session(engine) as session:
        sales_query = select(GlobalData).where(GlobalData.key == "total_sales")
        sales = session.exec(sales_query).one_or_none()
        return float(sales.value) if sales else 0.0


# add/update goods
@app.post("/v1/stocks")
async def post_goods(request: Request):
    # try to get the json data
    try:
        good_to_add = await request.json()
    except:
        return raise_error()

    # check the keys
    if not check_good_keys(good_to_add):
        return raise_error()

    # create a session to interact with the database
    with Session(engine) as session:
        # select the good from the database
        find_good = select(Goods).where(Goods.name == good_to_add["name"])
        existing_good = session.exec(find_good).one_or_none()

        # if the good exists, update the amount
        if existing_good:
            existing_good.amount += good_to_add.get("amount", 1)
            updated_good = existing_good
        else:
            # if the good does not exist, create a new one
            updated_good = Goods(
                name=good_to_add["name"],
                amount=good_to_add.get("amount", 1),
            )
            session.add(updated_good)

        # commit the changes to the database
        session.commit()
        # refresh the target good
        session.refresh(updated_good)

    return JSONResponse(
        content=good_to_add,
        status_code=status.HTTP_201_CREATED,
        headers={"Location": f"/v1/stocks/{good_to_add['name']}"},
    )


# get goods
# get one good
@app.get("/v1/stocks/{name}")
async def get_stock(name: str):
    with Session(engine) as session:
        # find the good
        find_good = select(Goods).where(Goods.name == name)
        existing_good = session.exec(find_good).one_or_none()
        # if the good exists, return the amount
        if existing_good:
            return_message = {f"{existing_good.name}": existing_good.amount}
        # if the good does not exist, return 0
        else:
            return_message = {f"{name}": 0}
        return return_message


# get all goods
@app.get("/v1/stocks")
async def get_stocks():
    with Session(engine) as session:
        # get all the goods
        goods = session.exec(select(Goods)).all()
        # sort the goods by name
        sorted_goods = sorted(goods, key=lambda good: good.name)
        # return the amount of the goods
        return_message = {}
        for good in sorted_goods:
            if good.amount:
                return_message[good.name] = good.amount
        return return_message


# sell goods
@app.post("/v1/sales")
async def sell_goods(request: Request):
    # try to get the json data
    try:
        good_to_sell = await request.json()
    except:
        return raise_error()

    # check the keys
    if not check_sale_keys(good_to_sell):
        return raise_error()

    with Session(engine) as session:
        # find the good
        find_good = select(Goods).where(Goods.name == good_to_sell["name"])
        existing_good = session.exec(find_good).one_or_none()

        if not existing_good:
            return raise_error()

        # get the amount to sell
        amount_to_sell = good_to_sell.get("amount", 1)

        # check if the amount to sell is greater than the amount of the good
        if existing_good.amount >= amount_to_sell:
            # update the sales
            sale_amount = float(good_to_sell.get("price", 0.0)) * amount_to_sell
            update_total_sales(session, sale_amount)
            # update the amount
            existing_good.amount -= amount_to_sell
            session.commit()
            session.refresh(existing_good)
        else:
            return raise_error()

        return JSONResponse(
            content=good_to_sell,
            status_code=status.HTTP_200_OK,
            headers={"Location": f"/v1/sales/{good_to_sell['name']}"},
        )


# get sales
@app.get("/v1/sales")
async def get_sales():
    sales = round(get_total_sales(), 2)
    return JSONResponse(
        content={"sales": sales},
        status_code=status.HTTP_200_OK,
    )


# delete all goods
@app.delete("/v1/stocks")
async def delete_goods():
    Goods.sales = 0.0
    with Session(engine) as session:
        goods = session.exec(select(Goods)).all()
        for good in goods:
            session.delete(good)
        session.commit()
    return JSONResponse(
        content={"message": "Stock deleted"},
        status_code=status.HTTP_200_OK,
    )


if __name__ == "__main__":
    uvicorn.run(app, port=8000)

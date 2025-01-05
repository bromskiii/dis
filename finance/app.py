import os
from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, jsonify
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from helpers import apology, login_required, lookup, usd

app = Flask(__name__)

app.jinja_env.filters["usd"] = usd

app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Initialize database
db = SQL("sqlite:///finance.db")

# Create portfolio table if not exists
db.execute("""
    CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        shares INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(user_id, symbol)
    );
""")

# Create transactions table if not exists
db.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        shares INTEGER NOT NULL,
        price REAL NOT NULL,
        transaction_type TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
""")

@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    user_id = session["user_id"]

    portfolio = db.execute(
        "SELECT symbol, shares FROM portfolio WHERE user_id = ?",
        user_id
    )

    cash = db.execute(
        "SELECT cash FROM users WHERE id = ?",
        user_id
    )[0]["cash"]

    total = cash
    for stock in portfolio:
        quote = lookup(stock["symbol"])
        stock["name"] = quote["name"]
        stock["price"] = quote["price"]
        stock["total"] = stock["shares"] * quote["price"]
        total += stock["total"]

    return render_template("index.html", portfolio=portfolio, cash=cash, total=total)

@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    if request.method == "POST":
        symbol = request.form.get("symbol").upper()
        shares = request.form.get("shares")

        # Validate inputs
        if not symbol:
            return apology("must provide symbol", 400)
        if not shares or not shares.isdigit() or int(shares) <= 0:
            return apology("must provide valid number of shares", 400)

        shares = int(shares)
        stock = lookup(symbol)
        if not stock:
            return apology("invalid symbol", 400)

        total_price = stock["price"] * shares
        user_id = session["user_id"]
        cash = db.execute("SELECT cash FROM users WHERE id = ?", user_id)[0]["cash"]

        if cash < total_price:
            return apology("can't afford", 400)

        # Record the transaction
        db.execute(
            "INSERT INTO transactions (user_id, symbol, shares, price, transaction_type) VALUES (?, ?, ?, ?, 'buy')",
            user_id, symbol, shares, stock["price"]
        )

        # Update portfolio
        portfolio = db.execute(
            "SELECT shares FROM portfolio WHERE user_id = ? AND symbol = ?", user_id, symbol
        )
        if len(portfolio) == 0:
            db.execute(
                "INSERT INTO portfolio (user_id, symbol, shares) VALUES (?, ?, ?)",
                user_id, symbol, shares
            )
        else:
            db.execute(
                "UPDATE portfolio SET shares = shares + ? WHERE user_id = ? AND symbol = ?",
                shares, user_id, symbol
            )

        # Deduct cash
        db.execute("UPDATE users SET cash = cash - ? WHERE id = ?", total_price, user_id)

        return redirect("/")  # Redirect back to home page

    else:
        # Render the buy page for GET requests
        stocks = db.execute("SELECT symbol, name, price FROM stocks")  # or wherever you're getting stock data
        return render_template("buy.html", stocks=stocks)

@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    rows = db.execute(
        """
        SELECT symbol, shares, price, transaction_type, timestamp
        FROM transactions
        WHERE user_id = ?
        ORDER BY timestamp DESC
        """,
        session["user_id"]
    )

    # Render the history page with the transactions data
    return render_template("history.html", transactions=rows)

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""
    session.clear()

    if request.method == "POST":
        if not request.form.get("username"):
            return apology("must provide username", 403)
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            return apology("invalid username and/or password", 403)

        session["user_id"] = rows[0]["id"]

        return redirect("/")
    else:
        return render_template("login.html")

@app.route("/logout")
def logout():
    """Log user out"""
    session.clear()
    return redirect("/")

@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        symbol = request.form.get("symbol").upper()

        if not symbol:
            return apology("must provide stock symbol", 400)

        stock = lookup(symbol)

        if not stock:
            return apology("invalid stock symbol", 400)

        return render_template("quoted.html", stock=stock)
    else:
        return render_template("quote.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if not username:
            return apology("must provide username", 400)
        if not password:
            return apology("must provide password", 400)

        rows = db.execute("SELECT * FROM users WHERE username = ?", username)
        if len(rows) > 0:
            return apology("username already taken", 400)

        password_hash = generate_password_hash(password)

        db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", username, password_hash)

        flash("Registered successfully! Please log in.")
        return redirect("/login")
    else:
        return render_template("registration.html")

@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "POST":
        symbol = request.form.get("symbol")
        shares = request.form.get("shares")

        if not symbol:
            return apology("must provide stock symbol", 400)
        if not shares or not shares.isdigit() or int(shares) <= 0:
            return apology("invalid number of shares", 400)

        shares = int(shares)

        # Check if the user has the stock in their portfolio
        rows = db.execute(
            "SELECT shares FROM portfolio WHERE user_id = ? AND symbol = ?",
            session["user_id"],
            symbol
        )

        if len(rows) != 1 or rows[0]["shares"] < shares:
            return apology("not enough shares", 400)

        stock = lookup(symbol)
        if not stock:
            return apology("invalid stock symbol", 400)

        sale_value = shares * stock["price"]

        # Update user's cash balance
        db.execute(
            "UPDATE users SET cash = cash + ? WHERE id = ?",
            sale_value,
            session["user_id"]
        )

        # If user sells all shares, remove the stock from portfolio
        if rows[0]["shares"] == shares:
            db.execute(
                "DELETE FROM portfolio WHERE user_id = ? AND symbol = ?",
                session["user_id"],
                symbol
            )
        else:
            db.execute(
                "UPDATE portfolio SET shares = shares - ? WHERE user_id = ? AND symbol = ?",
                shares,
                session["user_id"],
                symbol
            )

        # Add the transaction record
        db.execute(
            "INSERT INTO transactions (user_id, symbol, shares, price, transaction_type) VALUES (?, ?, ?, ?, ?)",
            session["user_id"],
            symbol,
            -shares,
            stock["price"],
            'sell'
        )

        flash("Sold!")
        return redirect("/")

    else:
        # Fetch all stock symbols from the user's portfolio to display in the dropdown
        rows = db.execute(
            "SELECT symbol FROM portfolio WHERE user_id = ?",
            session["user_id"]
        )

        return render_template("sell.html", symbols=[row["symbol"] for row in rows])

@app.route("/cash", methods=["GET", "POST"])
@login_required
def cash():
    """Add or withdraw cash from the account"""
    if request.method == "POST":
        action = request.form.get("action")
        amount = request.form.get("amount")

        # Validate the input
        if not amount or not amount.isdigit() or int(amount) <= 0:
            return apology("must provide a valid amount", 400)

        amount = int(amount)
        user_id = session["user_id"]

        if action == "add":
            db.execute("UPDATE users SET cash = cash + ? WHERE id = ?", amount, user_id)
        elif action == "withdraw":
            cash_balance = db.execute("SELECT cash FROM users WHERE id = ?", user_id)[0]["cash"]
            if cash_balance < amount:
                return apology("not enough cash", 400)
            db.execute("UPDATE users SET cash = cash - ? WHERE id = ?", amount, user_id)

        flash("Cash transaction successful!")
        return redirect("/")

    return render_template("cash.html")

if __name__ == "__main__":
    app.run()

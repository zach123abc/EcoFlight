import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Force Flask to always find templates/static relative to this app.py file
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
    static_url_path="/static",
)

# -----------------------------
# CONFIG
# -----------------------------

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev- secret")

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///schools.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = os.path.join(app.static_folder, "pictures")

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Create upload folder if not exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# -----------------------------
# GALLERY / UPLOAD HELPERS
# -----------------------------
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def list_gallery_images() -> list[str]:
    folder = app.config["UPLOAD_FOLDER"]
    if not os.path.isdir(folder):
        return []
    imgs = []
    for f in os.listdir(folder):
        if "." in f and f.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS:
            imgs.append(f)
    return sorted(imgs)

# -----------------------------
# DATABASE MODEL
# -----------------------------
class School(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    students = db.Column(db.Integer, nullable=False)
    points = db.Column(db.Float, default=1000)
    total_emissions = db.Column(db.Float, default=0)

    def score_per_student(self):
        if self.students == 0:
            return 0
        return round(self.points / self.students, 2)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(School, int(user_id))

_db_inited = False

def init_db_once():
    global _db_inited
    if _db_inited:
        return
    try:
        with app.app_context():
            db.create_all()
        _db_inited = True
    except Exception as e:
        print("DB init failed:", e)

# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def index():
    images = list_gallery_images()
    return render_template("index.html", images=images)

@app.route("/register", methods=["GET", "POST"])
def register():
    init_db_once()
    if request.method == "POST":
        try:
            name = request.form["name"]
            email = request.form["email"]
            password = request.form["password"]
            students = int(request.form["students"])
        except ValueError:
            flash("Students must be a whole number (e.g. 120).")
            return redirect(url_for("register"))
        except Exception:
            flash("Please fill in all fields correctly.")
            return redirect(url_for("register"))

        if School.query.filter_by(email=email).first():
            flash("Email already registered.")
            return redirect(url_for("register"))

        hashed = generate_password_hash(password)

        new_school = School(
            name=name,
            email=email,
            password=hashed,
            students=students,
        )

        db.session.add(new_school)
        db.session.commit()
        login_user(new_school)

        return redirect(url_for("dashboard"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    init_db_once()
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        school = School.query.filter_by(email=email).first()

        if school and check_password_hash(school.password, password):
            login_user(school)
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.")

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    init_db_once()
    images = list_gallery_images()
    return render_template("dashboard.html", school=current_user, images=images)

@app.route("/lowest-emission-flights")
def lowest_emission_flights():
    return render_template("lowest_emission_flights.html")

# -----------------------------
# ADD FLIGHT (NO AIRLINE FACTOR)
# -----------------------------
@app.route("/add_flight", methods=["POST"])
@login_required
def add_flight():
    init_db_once()
    try:
        distance = float(request.form["distance"])
        tim_estimate = float(request.form["tim"])
        luggage = float(request.form["luggage"])
        cabin_multiplier = float(request.form["cabin"])
        saf_percent = float(request.form["saf"])
    except ValueError:
        flash("Please enter numbers only (e.g. 1000, 250.5).")
        return redirect(url_for("dashboard"))
    except Exception:
        flash("Please fill in all flight fields.")
        return redirect(url_for("dashboard"))

    if distance < 0 or tim_estimate < 0 or luggage < 0 or cabin_multiplier <= 0:
        flash("Distance, TIM, luggage must be ≥ 0 and cabin multiplier must be > 0.")
        return redirect(url_for("dashboard"))

    if not (0 <= saf_percent <= 1):
        flash("SAF must be between 0 and 1 (example: 0.1 for 10%).")
        return redirect(url_for("dashboard"))

    luggage_co2 = (distance / 1000) * luggage * 0.5
    total_co2 = (tim_estimate + luggage_co2)
    total_co2 *= cabin_multiplier
    total_co2 *= (1 - saf_percent)

    points_deducted = total_co2 / 5

    current_user.points = max(current_user.points - points_deducted, 0)
    current_user.total_emissions += total_co2

    db.session.commit()
    return redirect(url_for("dashboard"))

# -----------------------------
# ADD ACTION (HARDER TO EARN BACK)
# -----------------------------
@app.route("/add_action", methods=["POST"])
@login_required
def add_action():
    init_db_once()
    try:
        action = request.form["action"]
        amount = float(request.form["amount"])
    except ValueError:
        flash("Amount must be a number (e.g. 5 or 2.5).")
        return redirect(url_for("dashboard"))
    except Exception:
        flash("Please fill in the action fields.")
        return redirect(url_for("dashboard"))

    if amount < 0:
        flash("Amount must be ≥ 0.")
        return redirect(url_for("dashboard"))

    # Harder rewards:
    # trash: +0.5 per kg
    # solar: diminishing returns -> points += floor(sqrt(kWh))
    # trees: +5 per tree
    if action == "trash":
        current_user.points += amount * 0.5
    elif action == "solar":
        current_user.points += int(amount ** 0.5)
    elif action == "tree":
        current_user.points += amount * 5
    else:
        flash("Unknown action type.")
        return redirect(url_for("dashboard"))

    db.session.commit()
    return redirect(url_for("dashboard"))

# -----------------------------
# IMAGE UPLOAD
# -----------------------------
@app.route("/upload", methods=["POST"])
@login_required
def upload():
    init_db_once()
    if "photo" not in request.files:
        flash("No file selected.")
        return redirect(url_for("dashboard"))

    file = request.files["photo"]

    if file.filename == "":
        flash("No file selected.")
        return redirect(url_for("dashboard"))

    if not allowed_file(file.filename):
        flash("Please upload an image file (jpg, png, webp, gif).")
        return redirect(url_for("dashboard"))

    filename = secure_filename(file.filename)
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

    flash("Image uploaded successfully.")
    return redirect(url_for("dashboard"))

# -----------------------------
# LEADERBOARD
# -----------------------------
@app.route("/leaderboard")
def leaderboard():
    init_db_once()
    schools = School.query.all()
    ranked = sorted(schools, key=lambda x: x.score_per_student(), reverse=True)
    return render_template("leaderboard.html", schools=ranked)

# -----------------------------
# START
# -----------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

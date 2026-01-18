import os
from flask import Flask, render_template, session, redirect, url_for
from dotenv import load_dotenv
from supabase import create_client

# 1. Gegevens laden uit .env
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# 2. Supabase koppelen
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# 3. De 'Route' voor je dashboard
@app.route('/')
def dashboard():
    # TEST: We doen alsof er een user is met 50 minuten
    test_credits = 50
    return render_template('index.html', minutes=test_credits)

if __name__ == '__main__':
    app.run(debug=True)  # debug=True zorgt dat de site herlaadt bij wijzigingen

import os
from flask import Flask, render_template, session, redirect, url_for, request, flash
from dotenv import load_dotenv
from supabase import create_client

# 1. Gegevens laden uit .env
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# 2. Supabase koppelen
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# =================================================================
# HELPER FUNCTIES (zelfde logica als je Streamlit app)
# =================================================================
def get_or_create_user_credits(user_email: str) -> dict:
    """Haalt user credits op, of maakt nieuwe user aan met 50 MB."""
    result = supabase.table('user_credits').select('*').eq('email', user_email).execute()

    if result.data:
        return result.data[0]
    else:
        new_user = supabase.table('user_credits').insert({
            'email': user_email,
            'credits_remaining_mb': 50.00
        }).execute()
        return new_user.data[0]

# =================================================================
# ROUTES
# =================================================================

@app.route('/')
def home():
    """Hoofdpagina - redirect naar dashboard of login"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login pagina met magic link"""
    # Als al ingelogd, ga naar dashboard
    if 'user' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        if email:
            try:
                # Stuur magic link (zelfde als in Streamlit)
                supabase.auth.sign_in_with_otp({
                    "email": email,
                    "options": {
                        "email_redirect_to": "http://127.0.0.1:5000/callback"
                    }
                })
                flash('Check je email voor de login link!', 'success')
            except Exception as e:
                flash(f'Fout bij verzenden: {str(e)}', 'error')
        else:
            flash('Vul een email adres in', 'error')

    return render_template('login.html')

@app.route('/callback')
def callback():
    """Toont de callback pagina die de hash fragment uitleest via JavaScript"""
    return render_template('callback.html')

@app.route('/auth/verify')
def auth_verify():
    """Verwerkt de token nadat JavaScript hem heeft doorgestuurd"""
    access_token = request.args.get('access_token')

    if access_token:
        try:
            # Verifieer de gebruiker met het token
            user_response = supabase.auth.get_user(access_token)

            if user_response and user_response.user:
                # Sla gebruiker op in Flask sessie
                session['user'] = {
                    'id': user_response.user.id,
                    'email': user_response.user.email
                }
                session['access_token'] = access_token
                flash('Succesvol ingelogd!', 'success')
                return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Login fout: {str(e)}', 'error')

    # Bij error, terug naar login
    flash('Login mislukt. Probeer opnieuw.', 'error')
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    """Dashboard - alleen voor ingelogde gebruikers"""
    if 'user' not in session:
        flash('Je moet eerst inloggen', 'error')
        return redirect(url_for('login'))

    user = session['user']

    # Haal credits op uit database
    try:
        user_credits = get_or_create_user_credits(user['email'])
        credits = float(user_credits['credits_remaining_mb'])
    except Exception as e:
        credits = 0
        flash(f'Kon credits niet laden: {str(e)}', 'error')

    return render_template('dashboard.html', user=user, credits=credits)

@app.route('/logout')
def logout():
    """Uitloggen - verwijder sessie"""
    session.clear()
    flash('Je bent uitgelogd', 'success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)

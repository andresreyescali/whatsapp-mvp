# En app.py, actualizar las rutas:

@app.route('/')
def landing():
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/admin/menu', methods=['GET'])
@login_required
@tenant_owner_required_from_args
def admin_menu():
    return render_template('menu.html')

@app.route('/admin/train', methods=['GET'])
@login_required
@tenant_owner_required_from_args
def train_ia_page():
    return render_template('train.html')
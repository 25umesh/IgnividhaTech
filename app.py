import os
import json
from datetime import datetime
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    flash,
    url_for,
    send_from_directory,
    abort,
)
from werkzeug.utils import secure_filename

# Initialize app
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# Uploads
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max upload
ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'docx', 'zip'
}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Simple storage using JSON files
REGISTRATIONS_FILE = 'registrations.json'
QUERIES_FILE = 'queries.json'


def allowed_file(filename):
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def save_file(file):
    if not file or not file.filename:
        return None
    if not allowed_file(file.filename):
        return None
    filename = secure_filename(file.filename)
    base, ext = os.path.splitext(filename)
    dest = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(dest):
        suffix = datetime.now().strftime('%Y%m%d%H%M%S%f')
        filename = f"{base}_{suffix}{ext}"
        dest = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(dest)
    return filename


def _load_list(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save_list(path, data_list):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data_list, f, ensure_ascii=False, indent=2)


def _require_admin():
    expected = os.environ.get('ADMIN_TOKEN')
    if expected:
        token = request.args.get('token')
        if token != expected:
            abort(403)


@app.route('/')
def home():
    return render_template('dashboard.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Basic info
        fullname = request.form.get('fullname')
        email = request.form.get('email')
        contact = request.form.get('contact')
        status = request.form.get('status')
        positions = request.form.getlist('position[]')

        if not fullname or not email or not contact or not status:
            flash("Please fill all required fields.", "error")
            return redirect(request.url)

        # Date of birth and age validation
        dob_str = request.form.get('dob')
        age_from_form = request.form.get('age')
        age = None
        try:
            if age_from_form:
                age = int(age_from_form)
            elif dob_str:
                dob = datetime.strptime(dob_str, '%Y-%m-%d')
                today = datetime.now()
                # compute age accounting for whether birthday passed this year
                age = (
                    today.year
                    - dob.year
                    - ((today.month, today.day) < (dob.month, dob.day))
                )
        except Exception:
            age = None

        if age is None:
            flash("Please provide a valid Date of Birth.", "error")
            return redirect(request.url)

        # Enforce age limits: 18 to 27 inclusive
        if age < 18 or age > 27:
            flash(
                (
                    f"Age {age} is not eligible. Applicants must be "
                    f"between 18 and 27 years old."
                ),
                "error",
            )
            return redirect(request.url)

        # Hackathon certificates (required at least one)
        hackathon_cert_files = request.files.getlist('hackathon_cert[]')
        hackathon_certificates = []
        for f in hackathon_cert_files:
            stored = save_file(f)
            if stored:
                hackathon_certificates.append(stored)
        if not hackathon_certificates:
            flash("Please upload at least one Hackathon certificate.", "error")
            return redirect(request.url)

        # College ID (students only)
        college_id_filename = None
        if status == 'Student':
            college_id_filename = save_file(request.files.get('college_id'))

        # Dynamic projects
        project_links = []
        project_files = []
        if status == 'Student':
            link_list = request.form.getlist(
                'studentProjectsContainer_project_link[]'
            )
            file_list = request.files.getlist(
                'studentProjectsContainer_project_file[]'
            )
        else:
            link_list = request.form.getlist(
                'graduateProjectsContainer_project_link[]'
            )
            file_list = request.files.getlist(
                'graduateProjectsContainer_project_file[]'
            )
        for i in range(max(len(link_list), len(file_list))):
            link = link_list[i] if i < len(link_list) else ''
            file = file_list[i] if i < len(file_list) else None
            if link:
                project_links.append(link)
            stored = save_file(file)
            if stored:
                project_files.append(stored)

        # Instagram proof (required)
        insta_filename = save_file(request.files.get('insta_follow_proof'))
        if not insta_filename:
            flash("Please upload Instagram follow proof.", "error")
            return redirect(request.url)

        # Socials
        social_media = {
            'github': request.form.get('github', ''),
            'linkedin': request.form.get('linkedin', ''),
            'instagram': request.form.get('instagram', ''),
            'portfolio': request.form.get('portfolio', ''),
        }

        # Load existing, assign id, save
        regs = _load_list(REGISTRATIONS_FILE)
        next_id = 1 + max([r.get('id', 0) for r in regs] or [0])
        registration = {
            'id': next_id,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'fullname': fullname,
            'email': email,
            'contact': contact,
            'age': age,
            'status': status,
            'positions': positions,
            'project_links': project_links,
            'project_files': project_files,
            'instagram_proof': insta_filename,
            'college_id': college_id_filename,
            'hackathon_certificates': hackathon_certificates,
            'social_media': social_media,
        }
        regs.insert(0, registration)
        _save_list(REGISTRATIONS_FILE, regs)

        flash("Registration submitted successfully!", "success")
        return redirect(url_for('register'))

    return render_template('register.html')


@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')
        if not name or not email or not message:
            flash("Please fill all fields.", "error")
            return redirect(request.url)

        qs = _load_list(QUERIES_FILE)
        qs.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'name': name,
            'email': email,
            'message': message,
        })
        _save_list(QUERIES_FILE, qs)
        flash("Your query has been submitted successfully!", "success")
        return redirect(url_for('contact'))

    return render_template('contact.html')


@app.route('/admin/registrations')
def view_registrations():
    _require_admin()
    regs = _load_list(REGISTRATIONS_FILE)
    return render_template('registrations.html', registrations=regs)


@app.route('/admin/registrations/delete/<int:reg_id>', methods=['POST'])
def delete_registration(reg_id):
    _require_admin()
    regs = _load_list(REGISTRATIONS_FILE)
    new_regs = [r for r in regs if r.get('id') != reg_id]
    _save_list(REGISTRATIONS_FILE, new_regs)
    flash('Registration deleted successfully!', 'success')
    return redirect(url_for('view_registrations'))


@app.route('/admin/queries')
def view_queries():
    _require_admin()
    qs = _load_list(QUERIES_FILE)
    return render_template('queries.html', queries=qs)


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)

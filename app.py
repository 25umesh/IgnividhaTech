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
    jsonify,
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables from .env file for local development
load_dotenv()

# Initialize app
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")


# --- DEPLOYMENT-READY STORAGE CONFIGURATION ---

# Use the persistent disk path from the hosting environment,
# or a local folder '.' if running locally
DATA_DIR = os.environ.get('RENDER_DISK_PATH', '.')

# 1. Define paths for your data files using the DATA_DIR
REGISTRATIONS_FILE = os.path.join(DATA_DIR, 'registrations.json')
QUERIES_FILE = os.path.join(DATA_DIR, 'queries.json')
UPDATES_FILE = os.path.join(DATA_DIR, 'updates.json')

# 2. Define path for file uploads using the DATA_DIR
UPLOAD_FOLDER = os.path.join(DATA_DIR, 'uploads')
os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True,
)  # Create the folder if it doesn't exist

# 3. Configure Flask to use the upload folder and set limits
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max upload
ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'docx', 'zip'
}
# --- END OF STORAGE CONFIGURATION ---


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
            data = json.load(f)
            # Backfill missing review_status as 'pending'
            if isinstance(data, list):
                for r in data:
                    if isinstance(r, dict) and 'review_status' not in r:
                        r['review_status'] = 'pending'
            return data
    except Exception:
        return []


def _save_list(path, data_list):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data_list, f, ensure_ascii=False, indent=2)


def _require_admin():
    expected = os.environ.get('ADMIN_TOKEN')
    if expected:
        token = (
            request.args.get('token')
            or request.form.get('token')
            or request.headers.get('X-Admin-Token')
        )
        if token != expected:
            abort(403)


def _load_updates_list():
    """Load updates from UPDATES_FILE or legacy notifications.json.
    Returns a list of strings, falling back to a default if empty.
    """
    data = []
    try:
        if os.path.exists(UPDATES_FILE):
            with open(UPDATES_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                if isinstance(raw, list):
                    for item in raw:
                        if isinstance(item, dict):
                            msg = (
                                item.get('message')
                                or item.get('text')
                                or item.get('title')
                            )
                            if msg:
                                data.append(str(msg))
                        else:
                            data.append(str(item))
        else:
            legacy_path = os.path.join(DATA_DIR, 'notifications.json')
            if os.path.exists(legacy_path):
                with open(legacy_path, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                    if isinstance(raw, list):
                        data = [str(x) for x in raw]
    except Exception:
        data = []

    if not data:
        data = ['Registration will open soon.']
    return data


@app.route('/')
def home():
    update_list = _load_updates_list()
    update = update_list[0] if update_list else 'Registration will open soon.'
    return render_template(
        'dashboard.html',
        update=update,
        updates=update_list,
    )


@app.route('/api/updates')
def api_updates():
    """Simple API to verify what updates the server sees."""
    return jsonify({'updates': _load_updates_list()})


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

        # Enforce 1-2 positions selected
        if len(positions) < 1 or len(positions) > 2:
            flash("Please select at least 1 and at most 2 positions.", "error")
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

        # Internship certificates (up to 10). Required for graduates,
        # optional for students.
        internship_cert_files = request.files.getlist('internship_cert[]')
        internship_certificates = []
        for f in internship_cert_files[:10]:
            stored = save_file(f)
            if stored:
                internship_certificates.append(stored)
        if status == 'Graduate' and not internship_certificates:
            flash(
                (
                    "Please upload at least one Internship certificate "
                    "(required for graduates)."
                ),
                "error",
            )
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

        # LinkedIn proof (required)
        linkedin_filename = save_file(
            request.files.get('linkedin_follow_proof')
        )
        if not linkedin_filename:
            flash("Please upload LinkedIn follow proof.", "error")
            return redirect(request.url)

        # Payment proof (required)
        payment_proof_filename = save_file(request.files.get('payment_proof'))
        if not payment_proof_filename:
            flash("Please upload payment proof.", "error")
            return redirect(request.url)

        # Profile photo (optional)
        profile_photo_filename = save_file(request.files.get('profile_photo'))

        # Socials (mandatory: GitHub, LinkedIn, Instagram)
        social_media = {
            'github': request.form.get('github', '').strip(),
            'linkedin': request.form.get('linkedin', '').strip(),
            'instagram': request.form.get('instagram', '').strip(),
            'portfolio': request.form.get('portfolio', '').strip(),
        }
        if (
            not social_media['github']
            or not social_media['linkedin']
            or not social_media['instagram']
        ):
            flash(
                "GitHub, LinkedIn, and Instagram profile links are required.",
                "error",
            )
            return redirect(request.url)

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
            # Admin review status options:
            # 'pending' | 'selected' | 'rejected' | 'paused'
            'review_status': 'pending',
            'positions': positions,
            'project_links': project_links,
            'project_files': project_files,
            'instagram_proof': insta_filename,
            'linkedin_proof': linkedin_filename,
            'payment_proof': payment_proof_filename,
            'profile_photo': profile_photo_filename,
            'college_id': college_id_filename,
            'hackathon_certificates': hackathon_certificates,
            'internship_certificates': internship_certificates,
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
    # Show only pending entries on the main registrations page
    regs = [
        r for r in _load_list(REGISTRATIONS_FILE)
        if r.get('review_status') == 'pending'
    ]
    return render_template('registrations.html', registrations=regs)


def _set_review_status(reg_id: int, new_status: str):
    regs = _load_list(REGISTRATIONS_FILE)
    updated = False
    for r in regs:
        if r.get('id') == reg_id:
            r['review_status'] = new_status
            updated = True
            break
    if updated:
        _save_list(REGISTRATIONS_FILE, regs)
    return updated


@app.route('/admin/registrations/select/<int:reg_id>', methods=['POST'])
def select_registration(reg_id):
    _require_admin()
    _set_review_status(reg_id, 'selected')
    flash('Marked as Selected.', 'success')
    token = request.args.get('token') or request.form.get('token')
    next_url = request.form.get('next') or request.args.get('next')
    if next_url and next_url.startswith('/'):
        return redirect(next_url)
    return redirect(url_for('view_selected', token=token))


@app.route('/admin/registrations/reject/<int:reg_id>', methods=['POST'])
def reject_registration(reg_id):
    _require_admin()
    _set_review_status(reg_id, 'rejected')
    flash('Marked as Rejected.', 'success')
    token = request.args.get('token') or request.form.get('token')
    next_url = request.form.get('next') or request.args.get('next')
    if next_url and next_url.startswith('/'):
        return redirect(next_url)
    return redirect(url_for('view_rejected', token=token))


@app.route('/admin/registrations/pause/<int:reg_id>', methods=['POST'])
def pause_registration(reg_id):
    _require_admin()
    _set_review_status(reg_id, 'paused')
    flash('Moved to Paused.', 'success')
    token = request.args.get('token') or request.form.get('token')
    next_url = request.form.get('next') or request.args.get('next')
    if next_url and next_url.startswith('/'):
        return redirect(next_url)
    return redirect(url_for('view_paused', token=token))


@app.route('/admin/selected')
def view_selected():
    _require_admin()
    regs = [
        r for r in _load_list(REGISTRATIONS_FILE)
        if r.get('review_status') == 'selected'
    ]
    return render_template('selected.html', registrations=regs)


@app.route('/admin/rejected')
def view_rejected():
    _require_admin()
    regs = [
        r for r in _load_list(REGISTRATIONS_FILE)
        if r.get('review_status') == 'rejected'
    ]
    return render_template('rejected.html', registrations=regs)


@app.route('/admin/paused')
def view_paused():
    _require_admin()
    regs = [
        r for r in _load_list(REGISTRATIONS_FILE)
        if r.get('review_status') == 'paused'
    ]
    return render_template('paused.html', registrations=regs)


@app.route('/admin/registrations/delete/<int:reg_id>', methods=['POST'])
def delete_registration(reg_id):
    _require_admin()
    regs = _load_list(REGISTRATIONS_FILE)
    new_regs = [r for r in regs if r.get('id') != reg_id]
    _save_list(REGISTRATIONS_FILE, new_regs)
    flash('Registration deleted successfully!', 'success')
    token = request.args.get('token') or request.form.get('token')
    next_url = request.form.get('next') or request.args.get('next')
    if next_url and next_url.startswith('/'):
        return redirect(next_url)
    return redirect(url_for('view_registrations', token=token))


@app.route('/admin/queries')
def view_queries():
    _require_admin()
    qs = _load_list(QUERIES_FILE)
    return render_template('queries.html', queries=qs)


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=True,
    )

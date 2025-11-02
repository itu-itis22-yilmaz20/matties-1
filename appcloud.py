# app.py — Matties (profil + avatar/bio + arkadaşlar + yenilemesiz beğeni)
import os, secrets
from flask import (
    Flask, request, jsonify, render_template_string,
    redirect, url_for, session, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import UniqueConstraint, or_, and_

# ---------------- APP / DB ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = "GIZLI_ANAHTAR"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///matties.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

ALLOWED_IMG = {"png", "jpg", "jpeg", "gif", "webp"}

# ---------------- MODELLER ----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200))   # uploads/ dosyası içindeki isim
    bio = db.Column(db.String(280), default="")
    posts = db.relationship("Post", backref="user", lazy=True)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    content = db.Column(db.Text)
    likes = db.Column(db.Integer, default=0)

class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(16), default="pending")  # pending | accepted
    __table_args__ = (UniqueConstraint("sender_id", "receiver_id", name="uq_friend_pair"),)

# ---------------- YARDIMCI ----------------
def current_user():
    uid = session.get("user_id")
    return User.query.get(uid) if uid else None

def are_friends(uid1, uid2) -> bool:
    if not uid1 or not uid2: return False
    f = Friendship.query.filter(
        or_(
            and_(Friendship.sender_id==uid1, Friendship.receiver_id==uid2),
            and_(Friendship.sender_id==uid2, Friendship.receiver_id==uid1)
        ),
        Friendship.status=="accepted"
    ).first()
    return f is not None

def pending_between(uid1, uid2):
    return Friendship.query.filter(
        or_(
            and_(Friendship.sender_id==uid1, Friendship.receiver_id==uid2),
            and_(Friendship.sender_id==uid2, Friendship.receiver_id==uid1)
        ),
        Friendship.status=="pending"
    ).first()

def file_allowed(filename:str)->bool:
    if "." not in filename: return False
    ext = filename.rsplit(".",1)[1].lower()
    return ext in ALLOWED_IMG

def avatar_url(u: User) -> str:
    if not u:
        return url_for("static_placeholder")
    return url_for("uploaded_file", filename=u.avatar) if u.avatar else url_for("static_placeholder")

# ---------------- DOSYA SERVİSİ ----------------
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.route("/static/placeholder.png")
def static_placeholder():
    # 1x1 şeffaf PNG
    from flask import Response
    data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x04\x00\x01\x0b\xe7\x02\x9e\x00\x00\x00\x00IEND\xaeB`\x82"
    return Response(data, mimetype="image/png")

# ---------------- SAYFALAR ----------------
@app.route("/")
def index():
    user = current_user()
    posts = Post.query.order_by(Post.id.desc()).all()
    incoming = []
    if user:
        incoming = Friendship.query.filter_by(receiver_id=user.id, status="pending").all()
    return render_template_string(PAGE, user=user, posts=posts, incoming=incoming, User=User, avatar_url=avatar_url)

@app.route("/register", methods=["POST"])
def register():
    u, p = request.form["username"].strip(), request.form["password"]
    if not u or not p: return "Kullanıcı adı/şifre boş olamaz."
    if User.query.filter_by(username=u).first():
        return "Bu kullanıcı adı zaten var."
    db.session.add(User(username=u, password=generate_password_hash(p)))
    db.session.commit()
    return redirect(url_for("login_page"))

@app.route("/login", methods=["GET","POST"])
def login_page():
    if request.method=="POST":
        u, p = request.form["username"], request.form["password"]
        user = User.query.filter_by(username=u).first()
        if user and check_password_hash(user.password, p):
            session["user_id"]=user.id
            return redirect(url_for("index"))
        return "Hatalı giriş."
    return render_template_string(LOGIN_PAGE)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/post", methods=["POST"])
def post():
    user = current_user()
    if not user: return redirect(url_for("login_page"))
    content = (request.form.get("content") or "").strip()
    if content:
        db.session.add(Post(user_id=user.id, content=content))
        db.session.commit()
    return redirect(url_for("index"))

# --------- PROFİL ---------
@app.route("/u/<username>")
def profile(username):
    owner = User.query.filter_by(username=username).first_or_404()
    viewer = current_user()
    status = "none"
    if viewer:
        if are_friends(viewer.id, owner.id): status = "friends"
        else:
            pend = pending_between(viewer.id, owner.id)
            if pend:
                status = "pending_from_me" if pend.sender_id==viewer.id else "pending_to_me"

    owner_posts = Post.query.filter_by(user_id=owner.id).order_by(Post.id.desc()).all()

    # Arkadaş listesi (accepted iki yön)
    friend_rels = Friendship.query.filter(
        or_(
            and_(Friendship.sender_id==owner.id, Friendship.status=="accepted"),
            and_(Friendship.receiver_id==owner.id, Friendship.status=="accepted")
        )
    ).limit(200).all()

    friend_ids = set()
    for f in friend_rels:
        friend_ids.add(f.receiver_id if f.sender_id==owner.id else f.sender_id)

    friends = User.query.filter(User.id.in_(list(friend_ids))).limit(50).all() if friend_ids else []

    return render_template_string(PROFILE_PAGE,
        user=viewer, owner=owner, posts=owner_posts, friends=friends, status=status, avatar_url=avatar_url
    )

@app.route("/profile/edit", methods=["GET","POST"])
def profile_edit():
    user = current_user()
    if not user: return redirect(url_for("login_page"))
    if request.method=="POST":
        user.bio = (request.form.get("bio") or "").strip()[:280]
        f = request.files.get("avatar")
        if f and f.filename and file_allowed(f.filename):
            ext = f.filename.rsplit(".",1)[1].lower()
            name = f"a_{user.id}_{secrets.token_hex(6)}.{ext}"
            f.save(os.path.join(UPLOAD_DIR, name))
            user.avatar = name
        db.session.commit()
        return redirect(url_for("profile", username=user.username))
    return render_template_string(EDIT_PAGE, user=user, avatar_url=avatar_url)

# --------- API: BEĞEN / ARKADAŞ ---------
@app.post("/api/like")
def api_like():
    user = current_user()
    if not user: return jsonify({"ok":False,"error":"auth"}), 401
    pid = request.json.get("post_id")
    post = Post.query.get(pid)
    if not post: return jsonify({"ok":False,"error":"notfound"}), 404
    post.likes = (post.likes or 0) + 1
    db.session.commit()
    return jsonify({"ok":True,"likes":post.likes})

@app.get("/api/search_users")
def api_search_users():
    user = current_user()
    if not user: return jsonify({"ok":False,"error":"auth"}), 401
    q = (request.args.get("q") or "").strip()
    if not q: return jsonify({"ok":True,"users":[]})
    results = User.query.filter(User.id!=user.id, User.username.ilike(f"%{q}%")).limit(20).all()
    out=[]
    for u in results:
        st="none"
        if are_friends(user.id, u.id): st="friends"
        else:
            pend = pending_between(user.id, u.id)
            if pend: st="pending_from_me" if pend.sender_id==user.id else "pending_to_me"
        out.append({"id":u.id,"username":u.username,"status":st})
    return jsonify({"ok":True,"users":out})

@app.post("/api/friend_request")
def api_friend_request():
    user = current_user()
    if not user: return jsonify({"ok":False,"error":"auth"}), 401
    rid = request.json.get("receiver_id")
    if not rid or rid==user.id: return jsonify({"ok":False,"error":"bad"}), 400
    if are_friends(user.id,rid) or pending_between(user.id,rid): return jsonify({"ok":True})
    db.session.add(Friendship(sender_id=user.id, receiver_id=rid, status="pending"))
    db.session.commit()
    return jsonify({"ok":True,"status":"pending"})

@app.post("/api/friend_accept")
def api_friend_accept():
    user = current_user()
    if not user: return jsonify({"ok":False,"error":"auth"}), 401
    sid = request.json.get("sender_id")
    fr = Friendship.query.filter_by(sender_id=sid, receiver_id=user.id, status="pending").first()
    if not fr: return jsonify({"ok":False,"error":"notfound"}), 404
    fr.status = "accepted"
    db.session.commit()
    return jsonify({"ok":True,"status":"accepted"})

# ---------------- TEMPLATES ----------------
PAGE = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<title>Matties</title>
<style>
body{font-family:Arial,system-ui;background:#80ff80;margin:0;}
#header{background:#1e7a1f;color:#fff;padding:10px;display:flex;gap:10px;align-items:center;}
#header a{color:#fff;text-decoration:underline;}
.container{padding:12px;}
.section{background:#eaffea;border-radius:12px;padding:12px;margin:12px 0;}
.post{background:#fff;border:1px solid #dcdcdc;margin:10px 0;padding:10px;border-radius:10px;}
.userline{display:flex;align-items:center;gap:8px;}
.userline img{width:28px;height:28px;border-radius:50%;object-fit:cover;border:1px solid #ccc;}
.username{font-weight:bold;color:#2e7d32;}
button{cursor:pointer;border:none;padding:7px 11px;border-radius:8px;background:#2e7d32;color:#fff;}
button.secondary{background:#555;}
input[type="text"],textarea{padding:8px;border-radius:8px;border:1px solid #aaa;width:100%;}
.result-row{display:flex;align-items:center;justify-content:space-between;background:#fff;border:1px solid #ddd;border-radius:10px;padding:8px;margin:6px 0;}
.badge{display:inline-block;background:#2e7d32;color:#fff;border-radius:999px;padding:2px 8px;font-size:12px;margin-left:6px;}
.chip{display:inline-flex;align-items:center;gap:6px;background:#fff;border:1px solid #bbb;border-radius:999px;padding:4px 10px;margin:4px;}
</style>
</head>
<body>
<div id="header" class="container">
  <div><b>Matties</b></div>
  <div style="flex:1"></div>
  {% if user %}
    <a href="{{ url_for('profile', username=user.username) }}">Profil</a>
    <a href="{{ url_for('logout') }}">Çıkış</a>
  {% else %}
    <a href="{{ url_for('login_page') }}">Giriş</a>
  {% endif %}
</div>

<div class="container">

{% if user %}
<div class="section">
  <form action="{{ url_for('post') }}" method="post">
    <textarea name="content" rows="3" placeholder="Bir şey paylaş..."></textarea><br><br>
    <button type="submit">Paylaş</button>
  </form>
</div>

<div class="section">
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
    <input id="searchBox" type="text" placeholder="Kullanıcı ara (en az 2 harf)…" style="max-width:300px;">
    <button id="searchBtn" class="secondary">Ara</button>
  </div>
  <div id="searchResults" style="margin-top:10px;"></div>
</div>

{% if incoming %}
<div class="section">
  <div><b>Bekleyen Davetler</b> <span class="badge">{{ incoming|length }}</span></div>
  <div id="incoming">
    {% for f in incoming %}
      {% set sender = User.query.get(f.sender_id) %}
      <div class="chip">
        <img src="{{ avatar_url(sender) }}" width="20" height="20" style="border-radius:50%;object-fit:cover;border:1px solid #ccc">
        @{{ sender.username }}
        <button data-sender="{{ f.sender_id }}" class="accept-btn">Kabul Et</button>
      </div>
    {% endfor %}
  </div>
</div>
{% endif %}
{% endif %}

<div class="section">
  <b>Gönderiler</b>
  {% for p in posts %}
    <div class="post">
      <div class="userline">
        <img src="{{ avatar_url(p.user) }}">
        <a href="{{ url_for('profile', username=p.user.username) }}" class="username">@{{ p.user.username }}</a>
      </div>
      <div style="margin:8px 0;white-space:pre-wrap">{{ p.content }}</div>
      <button class="like-btn" data-post-id="{{ p.id }}">Beğen ❤️ <span id="like-{{ p.id }}">{{ p.likes or 0 }}</span></button>
    </div>
  {% endfor %}
</div>

</div>

<script>
async function likePost(pid){
  const res = await fetch("/api/like",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({post_id:pid})});
  if(!res.ok) return;
  const data = await res.json();
  if(data.ok){
    const c=document.getElementById("like-"+pid);
    if(c) c.textContent=data.likes;
  }
}

async function searchUsers(q){
  const box = document.getElementById("searchResults");
  box.innerHTML = "Aranıyor…";
  const res = await fetch("/api/search_users?q="+encodeURIComponent(q));
  const data = await res.json();
  if(!data.ok){ box.textContent="Hata"; return; }
  if(data.users.length===0){ box.textContent="Sonuç yok."; return; }
  box.innerHTML="";
  for(const u of data.users){
    const row = document.createElement("div");
    row.className="result-row";
    const left = document.createElement("div");
    left.innerHTML = `<a class="clean" href="/u/${u.username}">@${u.username}</a>`;
    const right = document.createElement("div");
    if(u.status==="friends"){
      right.innerHTML = `<span class="badge">Arkadaşsınız</span>`;
    }else if(u.status==="pending_from_me"){
      right.innerHTML = `<span class="badge">Beklemede</span>`;
    }else if(u.status==="pending_to_me"){
      const b = document.createElement("button");
      b.textContent = "Kabul Et";
      b.onclick = async ()=>{
        const r = await fetch("/api/friend_accept",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sender_id:u.id})});
        const d = await r.json();
        if(d.ok){ searchUsers(q); }
      };
      right.appendChild(b);
    }else{
      const b = document.createElement("button");
      b.textContent = "İstek Gönder";
      b.onclick = async ()=>{
        const r = await fetch("/api/friend_request",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({receiver_id:u.id})});
        const d = await r.json();
        if(d.ok){ searchUsers(q); }
      };
      right.appendChild(b);
    }
    row.appendChild(left); row.appendChild(right); box.appendChild(row);
  }
}

document.addEventListener("click",(e)=>{
  const likeBtn = e.target.closest(".like-btn");
  if(likeBtn){ e.preventDefault(); likePost(likeBtn.dataset.postId); }
  const acceptBtn = e.target.closest(".accept-btn");
  if(acceptBtn){
    e.preventDefault();
    fetch("/api/friend_accept",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sender_id:acceptBtn.dataset.sender})})
      .then(r=>r.json()).then(d=>{ if(d.ok){ location.reload(); }});
  }
});
document.getElementById("searchBtn")?.addEventListener("click",()=>{
  const q = document.getElementById("searchBox").value.trim();
  if(q.length<2) return alert("En az 2 harf yaz.");
  searchUsers(q);
});
document.getElementById("searchBox")?.addEventListener("keydown",(e)=>{
  if(e.key==="Enter"){
    e.preventDefault();
    const q = e.target.value.trim();
    if(q.length<2) return;
    searchUsers(q);
  }
});
if("scrollRestoration" in history) history.scrollRestoration="manual";
</script>
</body>
</html>
"""

PROFILE_PAGE = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8"><title>@{{ owner.username }} • Profil</title>
<style>
body{font-family:Arial,system-ui;background:#80ff80;margin:0;}
#header{background:#1e7a1f;color:#fff;padding:10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
#header a{color:#fff;text-decoration:underline;}
.container{padding:12px;}
.card{background:#eaffea;border-radius:12px;padding:12px;margin:12px 0;}
.post{background:#fff;border:1px solid #dcdcdc;margin:10px 0;padding:10px;border-radius:10px;}
.usergrid{display:grid;grid-template-columns:72px 1fr;gap:12px;align-items:center;}
.usergrid img{width:72px;height:72px;border-radius:50%;object-fit:cover;border:2px solid #ccc;}
.username{font-weight:bold;font-size:20px;color:#2e7d32;}
.badge{display:inline-block;background:#2e7d32;color:#fff;border-radius:999px;padding:2px 8px;font-size:12px;margin-left:6px;}
button{cursor:pointer;border:none;padding:7px 11px;border-radius:8px;background:#2e7d32;color:#fff;}
button.secondary{background:#555;}
.friend-list{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;}
.friend-item{display:flex;align-items:center;gap:8px;background:#fff;border:1px solid #ddd;border-radius:999px;padding:6px 10px;}
.friend-item img{width:32px;height:32px;border-radius:50%;object-fit:cover;border:1px solid #ccc;}
a.clean{color:inherit;text-decoration:none;}
</style>
</head>
<body>
<div id="header" class="container">
  <div><a class="clean" href="{{ url_for('index') }}"><b>Matties</b></a></div>
  <div style="flex:1"></div>
  {% if user %}
    <a href="{{ url_for('profile', username=user.username) }}">Profilim</a>
    <a href="{{ url_for('logout') }}">Çıkış</a>
  {% else %}
    <a href="{{ url_for('login_page') }}">Giriş</a>
  {% endif %}
</div>

<div class="container">
  <div class="card">
    <div class="usergrid">
      <img src="{{ avatar_url(owner) }}">
      <div>
        <div class="username">@{{ owner.username }}
          {% if status=='friends' %}<span class="badge">Arkadaşsınız</span>{% elif status=='pending_from_me' %}<span class="badge">Beklemede</span>{% elif status=='pending_to_me' %}<span class="badge">Sana istek attı</span>{% endif %}
        </div>
        <div style="white-space:pre-wrap;opacity:.9;margin-top:4px;">{{ owner.bio or "Biyografi yok." }}</div>
        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
          {% if user and user.id != owner.id %}
            {% if status == 'none' %}
              <button id="addFriendBtn">Arkadaş Ekle</button>
            {% elif status == 'pending_to_me' %}
              <button id="acceptBtn">Kabul Et</button>
            {% endif %}
          {% endif %}
          {% if user and user.id == owner.id %}
            <a href="{{ url_for('profile_edit') }}"><button class="secondary">Profili Düzenle</button></a>
          {% endif %}
        </div>
      </div>
    </div>
  </div>

  <div class="card">
    <b>Arkadaşlar <small>({{ friends|length }})</small></b>
    <div class="friend-list">
      {% if friends %}
        {% for f in friends %}
          <a class="clean" href="{{ url_for('profile', username=f.username) }}">
            <div class="friend-item">
              <img src="{{ avatar_url(f) }}">
              <div>@{{ f.username }}</div>
            </div>
          </a>
        {% endfor %}
      {% else %}
        <div style="margin-top:8px;">Henüz arkadaş yok.</div>
      {% endif %}
    </div>
  </div>

  <div class="card">
    <b>Gönderiler</b>
    {% for p in posts %}
      <div class="post">
        <div style="white-space:pre-wrap">{{ p.content }}</div>
        <button class="like-btn" data-post-id="{{ p.id }}">Beğen ❤️ <span id="like-{{ p.id }}">{{ p.likes or 0 }}</span></button>
      </div>
    {% endfor %}
    {% if not posts %}<div>Gönderi yok.</div>{% endif %}
  </div>
</div>

<script>
async function likePost(pid){
  const res = await fetch("/api/like",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({post_id:pid})});
  if(!res.ok) return;
  const data = await res.json();
  if(data.ok){ const c=document.getElementById("like-"+pid); if(c) c.textContent=data.likes; }
}
document.addEventListener("click",(e)=>{
  const likeBtn = e.target.closest(".like-btn");
  if(likeBtn){ e.preventDefault(); likePost(likeBtn.dataset.postId); }
});
document.getElementById("addFriendBtn")?.addEventListener("click", async ()=>{
  const r = await fetch("/api/friend_request",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({receiver_id: {{ owner.id }}})});
  const d = await r.json(); if(d.ok) location.reload();
});
document.getElementById("acceptBtn")?.addEventListener("click", async ()=>{
  const r = await fetch("/api/friend_accept",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sender_id: {{ owner.id }}})});
  const d = await r.json(); if(d.ok) location.reload();
});
if("scrollRestoration" in history) history.scrollRestoration="manual";
</script>
</body>
</html>
"""

EDIT_PAGE = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8"><title>Profili Düzenle</title>
<style>
body{font-family:Arial,system-ui;background:#80ff80;margin:0;}
#header{background:#1e7a1f;color:#fff;padding:10px;display:flex;gap:10px;align-items:center;}
#header a{color:#fff;text-decoration:underline;}
.container{padding:12px;}
.card{background:#eaffea;border-radius:12px;padding:12px;margin:12px 0;}
input[type="file"],textarea{padding:8px;border-radius:8px;border:1px solid #aaa;width:100%;}
button{cursor:pointer;border:none;padding:7px 11px;border-radius:8px;background:#2e7d32;color:#fff;}
</style>
</head>
<body>
<div id="header" class="container">
  <div><a class="clean" href="{{ url_for('index') }}"><b>Matties</b></a></div>
  <div style="flex:1"></div>
  <a href="{{ url_for('profile', username=user.username) }}">Profil</a>
  <a href="{{ url_for('logout') }}">Çıkış</a>
</div>
<div class="container">
  <div class="card">
    <form action="" method="post" enctype="multipart/form-data">
      <div><b>Avatar</b></div>
      <div style="display:flex;gap:12px;align-items:center;margin:6px 0;">
        <img src="{{ avatar_url(user) }}" style="width:72px;height:72px;border-radius:50%;object-fit:cover;border:2px solid #ccc">
        <input type="file" name="avatar" accept=".png,.jpg,.jpeg,.gif,.webp">
      </div>
      <div style="margin-top:10px;">
        <b>Biyografi</b>
        <textarea name="bio" rows="4" maxlength="280" placeholder="Kısaca kendini anlat...">{{ user.bio }}</textarea>
      </div>
      <div style="margin-top:10px;">
        <button type="submit">Kaydet</button>
      </div>
    </form>
  </div>
</div>
</body>
</html>
"""

LOGIN_PAGE = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8"><title>Giriş</title>
<style>
body{font-family:Arial,system-ui;background:#80ff80;margin:0;}
.wrap{max-width:420px;margin:48px auto;background:#eaffea;border-radius:12px;padding:16px;border:1px solid #bcdcbc;}
input{padding:8px;border-radius:8px;border:1px solid #aaa;width:100%;}
button{cursor:pointer;border:none;padding:7px 11px;border-radius:8px;background:#2e7d32;color:#fff;}
</style>
</head>
<body>
<div class="wrap">
  <h2>Giriş / Kayıt</h2>
  <form method="post">
    <div>Kullanıcı adı</div>
    <input name="username">
    <div style="margin-top:8px;">Şifre</div>
    <input name="password" type="password">
    <div style="margin-top:12px;"><button type="submit">Giriş</button></div>
  </form>
  <hr style="margin:16px 0;">
  <form action="/register" method="post">
    <h3>Kayıt ol</h3>
    <div>Kullanıcı adı</div>
    <input name="username">
    <div style="margin-top:8px;">Şifre</div>
    <input name="password" type="password">
    <div style="margin-top:12px;"><button type="submit">Kayıt ol</button></div>
  </form>
</div>
</body>
</html>
"""

# ---------------- MAIN ----------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)

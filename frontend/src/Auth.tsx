import { useState } from 'react';
import { ArrowRight, Check, Code2, Eye, EyeOff, LockKeyhole, Mail, ShieldAlert, ShieldCheck, Sparkles, Swords, Trophy, UserRound } from 'lucide-react';
import { supabase, type User } from './api';
import { ThemeToggle } from './theme';

export function LogoPair() {
  return (
    <span className="logo-pair">
      <img src="/uet-logo.webp" alt="Logo Trường Đại học Công nghệ (UET)" />
      <img src="/fit-logo.png" alt="Logo Khoa Công nghệ thông tin (FIT)" />
    </span>
  );
}

export function Brand() {
  return (
    <a className="brand" href="/">
      <LogoPair />
      <span className="brand-text">UET<span className="brand-light">_RPS</span><small>CODE. COMPETE. CONQUER.</small></span>
    </a>
  );
}

export default function Auth({ onLogin }: { onLogin: (user: User) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [verifyNotice, setVerifyNotice] = useState<string | null>(null);

  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const changeMode = (next: 'login' | 'register') => {
    setMode(next);
    setError('');
    setSuccessMsg('');
    setVerifyNotice(null);
  };

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    setSuccessMsg('');

    try {
      const { data, error: authError } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      });

      if (authError) {
        if (authError.message.toLowerCase().includes('email not confirmed')) {
          setError('Email của bạn chưa được xác thực. Vui lòng kiểm tra hộp thư đến (hoặc mục Spam).');
          return;
        }
        if (authError.message.toLowerCase().includes('invalid login credentials')) {
          setError('Email hoặc mật khẩu không chính xác.');
          return;
        }
        throw authError;
      }

      if (data.user) {
        // Lấy profile từ Supabase
        const { data: profile } = await supabase
          .from('profiles')
          .select('username, role')
          .eq('id', data.user.id)
          .single();

        const name = profile?.username || data.user.user_metadata?.username || email.split('@')[0];
        const role = profile?.role || 'contestant';

        onLogin({
          id: data.user.id,
          email: data.user.email,
          name,
          role,
        });
      }
    } catch (err: any) {
      setError(err?.message || 'Đăng nhập không thành công. Vui lòng thử lại.');
    } finally {
      setBusy(false);
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirmPassword) {
      setError('Mật khẩu xác nhận chưa khớp.');
      return;
    }
    if (!/^[A-Za-z0-9_]{3,20}$/.test(username.trim())) {
      setError('Tên người dùng cần 3–20 ký tự (chữ, số hoặc gạch dưới).');
      return;
    }

    setBusy(true);
    setError('');
    setSuccessMsg('');

    try {
      const { data, error: signUpError } = await supabase.auth.signUp({
        email: email.trim(),
        password,
        options: {
          data: {
            username: username.trim(),
          },
        },
      });

      if (signUpError) throw signUpError;

      if (data.user && !data.session) {
        // Yêu cầu xác thực qua email
        setVerifyNotice(email.trim());
      } else if (data.user && data.session) {
        // Tự động đăng nhập nếu không yêu cầu email confirmation
        const name = data.user.user_metadata?.username || username.trim();
        onLogin({
          id: data.user.id,
          email: data.user.email,
          name,
          role: 'contestant',
        });
      }
    } catch (err: any) {
      setError(err?.message || 'Đăng ký thất bại. Vui lòng thử lại.');
    } finally {
      setBusy(false);
    }
  }

  async function handleResendVerification() {
    if (!email) {
      setError('Vui lòng nhập email để gửi lại xác thực.');
      return;
    }
    setBusy(true);
    try {
      const { error: resendError } = await supabase.auth.resend({
        type: 'signup',
        email: email.trim(),
      });
      if (resendError) throw resendError;
      setSuccessMsg('Đã gửi lại email xác thực. Vui lòng kiểm tra hộp thư!');
    } catch (err: any) {
      setError(err?.message || 'Không thể gửi lại email xác thực.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-layout">
      <section className="auth-story">
        <Brand />
        <div className="story-body">
          <span className="pill"><span className="live-dot" /> ĐẤU TRƯỜNG BOT RPS</span>
          <h1>Mỗi nước đi.<br />Một <span>chiến thuật.</span></h1>
          <p>Biến ý tưởng thành thuật toán. Đưa bot của bạn lên bàn cờ và chinh phục đấu trường.</p>
          <div className="game-art" aria-label="Minh họa bàn cờ bot RPS">
            <div className="art-top"><span><span className="live-dot" /> BOT ARENA</span><span>9 × 9 BOARD</span></div>
            <div className="mini-board">
              {Array.from({ length: 49 }, (_, i) => (
                <div key={i} className={(Math.floor(i / 7) + i % 7) % 2 ? 'shade' : ''}>
                  {({ 3: '✊', 9: '✌️', 15: '🖐', 24: '✊', 33: '✌️', 39: '🖐', 45: '✊' } as Record<number, string>)[i] && (
                    <span className={`art-piece ${i > 24 ? 'violet' : 'blue'}`}>
                      {({ 3: '✊', 9: '✌️', 15: '🖐', 24: '✊', 33: '✌️', 39: '🖐', 45: '✊' } as Record<number, string>)[i]}
                    </span>
                  )}
                </div>
              ))}
            </div>
            <div className="floating-tag">
              <Code2 size={17} />
              <span>Thuật toán của bạn.<br /><strong>Dấu ấn của bạn.</strong></span>
              <Sparkles size={18} />
            </div>
          </div>
          <div className="story-features">
            <span><Code2 /> Viết bot Python</span>
            <span><Swords /> Thi đấu BO2</span>
            <span><Trophy /> Leo bảng xếp hạng</span>
          </div>
        </div>
        <footer><span className="footer-logos"><img src="/uet-logo.webp" alt="UET" /><img src="/fit-logo.png" alt="FIT" /><b>UET_RPS</b></span><span>Không ngừng học hỏi. Không ngừng tiến bộ.</span></footer>
      </section>

      <section className="auth-panel">
        <div className="auth-top">
          <span className="badge"><span className="live-dot" /> XÁC THỰC TÀI KHOẢN</span>
          <ThemeToggle showLabel />
        </div>

        <div className="auth-card">
          <span className="form-icon">{mode === 'register' ? <Sparkles /> : <LockKeyhole />}</span>
          <p className="eyebrow">SẴN SÀNG CHO THỬ THÁCH?</p>
          <h2>{mode === 'register' ? 'Bắt đầu hành trình.' : 'Chào mừng trở lại.'}</h2>
          <p>
            {mode === 'register'
              ? 'Tạo tài khoản thí sinh và xác thực qua email để gia nhập đấu trường.'
              : 'Đăng nhập bằng Email và mật khẩu của bạn để tiếp tục.'}
          </p>

          <div className="auth-tabs" role="tablist" aria-label="Tài khoản">
            <button
              role="tab"
              aria-selected={mode === 'login'}
              className={mode === 'login' ? 'selected' : ''}
              onClick={() => changeMode('login')}
              disabled={busy}
            >
              Đăng nhập
            </button>
            <button
              role="tab"
              aria-selected={mode === 'register'}
              className={mode === 'register' ? 'selected' : ''}
              onClick={() => changeMode('register')}
              disabled={busy}
            >
              Tạo tài khoản
            </button>
          </div>

          {verifyNotice ? (
            <div className="verify-card" style={{ padding: '20px 0', textAlign: 'center' }}>
              <div style={{ display: 'inline-flex', padding: '14px', borderRadius: 0, background: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6', marginBottom: '12px' }}>
                <Mail size={36} />
              </div>
              <h3 style={{ fontSize: '1.2rem', margin: '8px 0' }}>Kiểm tra hòm thư của bạn!</h3>
              <p style={{ color: 'var(--text-muted, #94a3b8)', fontSize: '0.92rem', lineHeight: '1.5' }}>
                Chúng tôi đã gửi email xác thực tới <strong>{verifyNotice}</strong>.<br />
                Vui lòng mở email và nhấn vào liên kết xác nhận để kích hoạt tài khoản.
              </p>
              <div style={{ marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <button
                  type="button"
                  className="primary"
                  onClick={() => {
                    setVerifyNotice(null);
                    setMode('login');
                  }}
                >
                  Đến màn hình Đăng nhập
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={handleResendVerification}
                >
                  {busy ? 'Đang gửi lại...' : 'Chưa nhận được? Gửi lại email'}
                </button>
              </div>
            </div>
          ) : (
            <form key={mode} onSubmit={mode === 'login' ? handleLogin : handleRegister}>
              <fieldset disabled={busy}>
                <label>
                  Email
                  <div className="input-wrap">
                    <Mail size={18} />
                    <input
                      name="email"
                      type="email"
                      required
                      autoComplete="email"
                      placeholder="vidu@domain.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </div>
                </label>

                {mode === 'register' && (
                  <label>
                    Tên tài khoản (Username)
                    <div className="input-wrap">
                      <UserRound size={18} />
                      <input
                        name="username"
                        required
                        minLength={3}
                        maxLength={20}
                        pattern="[A-Za-z0-9_]{3,20}"
                        autoComplete="username"
                        placeholder="ten_thi_sinh"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                      />
                    </div>
                    <small>3–20 ký tự, gồm chữ, số hoặc dấu gạch dưới.</small>
                  </label>
                )}

                <label>
                  Mật khẩu
                  <div className="input-wrap">
                    <LockKeyhole size={18} />
                    <input
                      name="password"
                      required
                      minLength={8}
                      maxLength={72}
                      autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                      type={show ? 'text' : 'password'}
                      placeholder={mode === 'register' ? 'Tối thiểu 8 ký tự' : 'Nhập mật khẩu'}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                    <button
                      className="icon-button"
                      type="button"
                      aria-label={show ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}
                      onClick={() => setShow(!show)}
                    >
                      {show ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                </label>

                {mode === 'register' && (
                  <>
                    <div className="password-meter">
                      <i className={password.length >= 8 ? 'filled' : ''} />
                      <i className={password.length >= 10 ? 'filled' : ''} />
                      <i className={password.length >= 10 && /[0-9]/.test(password) && /[^A-Za-z0-9]/.test(password) ? 'filled' : ''} />
                    </div>
                    <label>
                      Xác nhận mật khẩu
                      <div className="input-wrap">
                        <ShieldCheck size={18} />
                        <input
                          name="confirm"
                          type={show ? 'text' : 'password'}
                          required
                          minLength={8}
                          maxLength={72}
                          autoComplete="new-password"
                          placeholder="Nhập lại mật khẩu"
                          value={confirmPassword}
                          onChange={(e) => setConfirmPassword(e.target.value)}
                        />
                      </div>
                    </label>
                  </>
                )}

                {error && (
                  <div className="form-error" role="alert" style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <span>{error}</span>
                    {error.includes('chưa được xác thực') && (
                      <button
                        type="button"
                        style={{ background: 'none', border: 'none', color: '#60a5fa', textDecoration: 'underline', cursor: 'pointer', textAlign: 'left', padding: 0 }}
                        onClick={handleResendVerification}
                      >
                        Bấm vào đây để gửi lại email xác thực
                      </button>
                    )}
                  </div>
                )}

                {successMsg && (
                  <div className="success" role="status" style={{ marginBottom: '14px' }}>
                    <Check size={18} /> {successMsg}
                  </div>
                )}

                <button className="primary auth-submit" type="submit" disabled={busy}>
                  {busy ? 'Đang xử lý…' : mode === 'register' ? 'Tạo tài khoản & Nhận mã' : 'Vào đấu trường'}
                  {!busy && <ArrowRight size={18} />}
                </button>
              </fieldset>
            </form>
          )}

          <div style={{ marginTop: '20px', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '16px' }}>
            <p className="secure-note" style={{ fontSize: '0.82rem', color: '#94a3b8' }}>
              <ShieldAlert size={15} style={{ flexShrink: 0 }} />
              <strong>Ban tổ chức:</strong> Tài khoản quản trị được cấp riêng. Hãy đăng nhập bằng email đã được cung cấp.
            </p>
          </div>
        </div>

        <div className="auth-bottom">
          <span><Check size={14} /> Sáng tạo chiến thuật</span>
          <span><Check size={14} /> Cạnh tranh công bằng</span>
        </div>
      </section>
    </div>
  );
}

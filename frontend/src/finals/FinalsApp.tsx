import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Crown,
  Eye,
  EyeOff,
  LayoutDashboard,
  LogIn,
  LogOut,
  Medal,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Search,
  Shield,
  Swords,
  Trophy,
  UserRound,
  Users,
  X,
} from 'lucide-react';

type Tab = 'overview' | 'matches' | 'live' | 'contestants' | 'admin';
type MatchStatus = 'pending' | 'running' | 'done' | 'failed';
type Standing = {
  username: string;
  wins: number;
  losses: number;
  draws: number;
  points: number;
  updated_at: string;
};
type Match = {
  id: number;
  request_id: string;
  player_a: string;
  player_b: string;
  status: MatchStatus;
  score_a: number | null;
  score_b: number | null;
  winner: string | null;
  error_msg?: string | null;
  created_at: string;
};
type Contestant = {
  username: string;
  display_name: string;
  student_id: string | null;
  created_at: string;
};
type User = {
  username: string;
  display_name: string;
  student_id: string | null;
};
type GameMove = [number, [number, number, number, number]];
type Game = {
  players: ['a' | 'b', 'a' | 'b'];
  moves: GameMove[];
};
type QueueInfo = { queue_size: number; max_workers: number; pending_db: number };
type ApiResult<T> = { ok: boolean; error?: string } & T;
type Toast = { message: string; error?: boolean } | null;

const TOKEN_KEY = 'finals_token';
const ADMIN_KEY = 'finals_admin_secret';
const NAV_ITEMS: { id: Tab; label: string; icon: typeof LayoutDashboard }[] = [
  { id: 'overview', label: 'Tổng quan', icon: LayoutDashboard },
  { id: 'matches', label: 'Trận đấu', icon: Swords },
  { id: 'live', label: 'Xem trực tiếp', icon: Radio },
  { id: 'contestants', label: 'Thí sinh', icon: Users },
  { id: 'admin', label: 'Ban tổ chức', icon: Shield },
];
const PIECES = ['✊', '✋', '✌️'];

async function api<T>(
  path: string,
  options: RequestInit = {},
  adminSecret = '',
): Promise<ApiResult<T>> {
  const token = localStorage.getItem(TOKEN_KEY) || '';
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { 'X-Finals-Token': token } : {}),
      ...(adminSecret ? { 'X-Admin-Secret': adminSecret } : {}),
      ...options.headers,
    },
  });
  const result = (await response.json()) as ApiResult<T>;
  if (!response.ok || !result.ok) {
    throw new Error(result.error || `Yêu cầu thất bại (${response.status})`);
  }
  return result;
}

function formatDate(value?: string | null, time = false) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? '—'
    : new Intl.DateTimeFormat('vi-VN', time
      ? { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' }
      : { day: '2-digit', month: '2-digit', year: 'numeric' }).format(date);
}

function initials(name: string) {
  return name.trim().slice(0, 2).toUpperCase() || 'OT';
}

function StatusPill({ status }: { status: MatchStatus }) {
  const labels: Record<MatchStatus, string> = {
    pending: 'Đang chờ',
    running: 'Đang thi đấu',
    done: 'Hoàn tất',
    failed: 'Thất bại',
  };
  return (
    <span className={`finals-status finals-status-${status}`}>
      {status === 'running' && <span className="finals-status-dot" />}
      {labels[status]}
    </span>
  );
}

export default function FinalsApp() {
  const [tab, setTab] = useState<Tab>('overview');
  const [standings, setStandings] = useState<Standing[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [contestants, setContestants] = useState<Contestant[]>([]);
  const [queue, setQueue] = useState<QueueInfo | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [adminSecret, setAdminSecret] = useState(() => localStorage.getItem(ADMIN_KEY) || '');
  const [toast, setToast] = useState<Toast>(null);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [games, setGames] = useState<Game[]>([]);
  const [gameIndex, setGameIndex] = useState(0);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [live, setLive] = useState(false);
  const [feed, setFeed] = useState<string[]>([]);
  const [showAdminSecret, setShowAdminSecret] = useState(false);
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  const [matchForm, setMatchForm] = useState({
    playerA: '',
    playerB: '',
    requestId: '',
    liveDelay: '0.4',
    autoLive: true,
  });
  const [contestantForm, setContestantForm] = useState({
    username: '',
    password: '',
    displayName: '',
    studentId: '',
  });

  const notify = useCallback((message: string, error = false) => {
    setToast({ message, error });
    window.setTimeout(() => setToast(null), 4000);
  }, []);

  const loadPublicData = useCallback(async () => {
    try {
      const [standingData, matchData] = await Promise.all([
        api<{ standings: Standing[] }>('/finals/standings'),
        api<{ matches: Match[]; total: number }>('/finals/matches?per_page=50'),
      ]);
      setStandings(standingData.standings);
      setMatches(matchData.matches);
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Không thể tải dữ liệu chung kết.', true);
    }
  }, [notify]);

  const loadAdminData = useCallback(async () => {
    if (!adminSecret.trim()) return;
    try {
      const [contestantData, queueData] = await Promise.all([
        api<{ contestants: Contestant[] }>('/finals/admin/contestants', {}, adminSecret),
        api<{ queue: QueueInfo }>('/finals/admin/queue', {}, adminSecret),
      ]);
      setContestants(contestantData.contestants);
      setQueue(queueData.queue);
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Không thể tải dữ liệu ban tổ chức.', true);
    }
  }, [adminSecret, notify]);

  useEffect(() => {
    void loadPublicData();
    const interval = window.setInterval(() => void loadPublicData(), 15000);
    return () => window.clearInterval(interval);
  }, [loadPublicData]);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) return;
    void api<{ user: User }>('/finals/me')
      .then((data) => setUser(data.user))
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setUser(null);
      });
  }, []);

  useEffect(() => {
    if (tab !== 'admin' && tab !== 'contestants') return;
    void loadAdminData();
  }, [tab, loadAdminData]);

  const selectedMatch = matches.find((match) => match.request_id === selectedId) ?? null;
  const currentGame = games[gameIndex];
  const currentMoves = currentGame?.moves ?? [];
  const visibleMatches = matches.filter((match) => {
    const query = search.toLowerCase();
    return `${match.player_a} ${match.player_b} ${match.request_id}`.toLowerCase().includes(query);
  });

  const loadReplay = useCallback(async (requestId: string) => {
    try {
      const data = await api<{ match: Match & { replay?: Game[] | null } }>(
        `/finals/matches/${encodeURIComponent(requestId)}/replay`,
      );
      const replay = data.match.replay ?? [];
      setGames(replay);
      setGameIndex(0);
      setStep(0);
      setLive(false);
      setFeed([`Đang xem lại ${data.match.player_a} đấu với ${data.match.player_b}.`]);
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Không thể tải dữ liệu xem lại.', true);
    }
  }, [notify]);

  useEffect(() => {
    if (!selectedMatch || (selectedMatch.status !== 'running' && selectedMatch.status !== 'pending')) {
      return;
    }
    setGames([
      { players: ['a', 'b'], moves: [] },
      { players: ['b', 'a'], moves: [] },
    ]);
    setGameIndex(0);
    setStep(0);
    setLive(true);
    setFeed(['Đang kết nối kênh phát trực tiếp…']);
    const source = new EventSource(`/finals/matches/${encodeURIComponent(selectedMatch.request_id)}/live`);
    source.onmessage = (message) => {
      if (!message.data) return;
      try {
        const event = JSON.parse(message.data) as {
          type: string;
          player_a?: string;
          player_b?: string;
          game?: number;
          player?: number;
          move?: [number, number, number, number];
          mover?: string;
          ply?: number;
          is_win?: boolean;
          score_a?: number;
          score_b?: number;
          winner?: string | null;
          games?: Game[];
          error?: string;
        };
        if (event.type === 'connected') {
          setFeed((previous) => [...previous, 'Đã kết nối — sẵn sàng theo dõi trận đấu.']);
        } else if (event.type === 'match_start') {
          setFeed((previous) => [...previous, `Trận đấu bắt đầu: ${event.player_a} vs ${event.player_b}.`]);
        } else if (event.type === 'move' && event.move && event.game !== undefined && event.player !== undefined) {
          const matchGame = event.game;
          const move: GameMove = [event.player, event.move];
          setGames((previous) => previous.map((game, index) => index === matchGame
            ? { ...game, moves: [...game.moves, move] }
            : game));
          setGameIndex(matchGame);
          setStep((previous) => previous + 1);
          const [x, y, nextX, nextY] = event.move;
          const columns = 'abcdefghi';
          setFeed((previous) => [
            ...previous,
            `${event.mover ?? 'Thí sinh'} · ${columns[x]}${y + 1} → ${columns[nextX]}${nextY + 1}${event.is_win ? ' · Chiến thắng!' : ''}`,
          ]);
        } else if (event.type === 'match_end') {
          setLive(false);
          setGames(event.games ?? []);
          setGameIndex(0);
          setStep(0);
          setFeed((previous) => [
            ...previous,
            event.winner
              ? `Trận đấu kết thúc · ${event.winner} giành chiến thắng (${event.score_a}–${event.score_b}).`
              : `Trận đấu kết thúc hòa (${event.score_a}–${event.score_b}).`,
          ]);
          void loadPublicData();
          source.close();
        } else if (event.type === 'match_failed') {
          setLive(false);
          setFeed((previous) => [...previous, `Trận đấu gặp lỗi: ${event.error ?? 'Không rõ nguyên nhân'}`]);
          source.close();
        }
      } catch {
        setFeed((previous) => [...previous, 'Không đọc được dữ liệu phát trực tiếp.']);
      }
    };
    source.onerror = () => {
      setFeed((previous) => previous[previous.length - 1] === 'Đang kết nối lại kênh trực tiếp…'
        ? previous
        : [...previous, 'Đang kết nối lại kênh trực tiếp…']);
    };
    return () => source.close();
  }, [selectedMatch?.request_id, selectedMatch?.status, loadPublicData]);

  useEffect(() => {
    if (!playing || live) return;
    const interval = window.setInterval(() => {
      setStep((current) => {
        if (current >= currentMoves.length) {
          setPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, 520);
    return () => window.clearInterval(interval);
  }, [playing, live, currentMoves.length]);

  const boardPieces = useMemo(() => {
    const game = currentGame;
    if (!game) return new Map<string, { icon: string; owner: 'a' | 'b' }>();
    const board = new Map<string, { icon: string; owner: 'a' | 'b' }>();
    for (let x = 0; x < 9; x += 1) {
      board.set(`${x},0`, { icon: PIECES[x % 3], owner: game.players[0] });
      board.set(`${x},8`, { icon: PIECES[x % 3], owner: game.players[1] });
    }
    for (const [player, move] of currentMoves.slice(0, step)) {
      const [x, y, nextX, nextY] = move;
      const piece = board.get(`${x},${y}`);
      board.delete(`${x},${y}`);
      if (piece) board.set(`${nextX},${nextY}`, { ...piece, owner: game.players[player] });
    }
    return board;
  }, [currentGame, currentMoves, step]);

  async   function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      const data = await api<{ token: string }>('/finals/auth/login', {
        method: 'POST',
        body: JSON.stringify(loginForm),
      });
      localStorage.setItem(TOKEN_KEY, data.token);
      const profile = await api<{ user: User }>('/finals/me');
      setUser(profile.user);
      setLoginForm({ username: '', password: '' });
      notify('Đăng nhập thành công.');
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Không thể đăng nhập.', true);
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    try {
      await api('/finals/auth/logout', { method: 'POST' });
    } catch {
      // Xoá thông tin phiên ở trình duyệt kể cả khi server đã hết phiên.
    }
    localStorage.removeItem(TOKEN_KEY);
    setUser(null);
    notify('Đã đăng xuất.');
  }

  async function createMatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      const data = await api<{ request_id: string }>('/finals/matches', {
        method: 'POST',
        body: JSON.stringify({
          player_a: matchForm.playerA.trim(),
          player_b: matchForm.playerB.trim(),
          request_id: matchForm.requestId.trim() || undefined,
          live_delay: Number(matchForm.liveDelay),
        }),
      }, adminSecret);
      localStorage.setItem(ADMIN_KEY, adminSecret);
      await loadPublicData();
      await loadAdminData();
      setSelectedId(data.request_id);
      setTab(matchForm.autoLive ? 'live' : 'matches');
      setMatchForm((current) => ({ ...current, playerA: '', playerB: '', requestId: '' }));
      notify('Đã đưa trận đấu vào hàng đợi.');
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Không thể tạo trận đấu.', true);
    } finally {
      setBusy(false);
    }
  }

  async function addContestant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      await api('/finals/admin/contestants', {
        method: 'POST',
        body: JSON.stringify({
          username: contestantForm.username.trim(),
          password: contestantForm.password,
          display_name: contestantForm.displayName.trim(),
          student_id: contestantForm.studentId.trim() || null,
        }),
      }, adminSecret);
      localStorage.setItem(ADMIN_KEY, adminSecret);
      setContestantForm({ username: '', password: '', displayName: '', studentId: '' });
      await loadAdminData();
      notify('Đã thêm thí sinh mới.');
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Không thể thêm thí sinh.', true);
    } finally {
      setBusy(false);
    }
  }

  async function snapshotBot(username: string) {
    try {
      await api('/finals/admin/bots/snapshot', {
        method: 'POST',
        body: JSON.stringify({ username }),
      }, adminSecret);
      notify(`Đã chốt bot cho ${username}.`);
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Không thể chốt bot.', true);
    }
  }

  function openMatch(match: Match) {
    setSelectedId(match.request_id);
    setTab('live');
    setPlaying(false);
    if (match.status === 'done') void loadReplay(match.request_id);
  }

  function selectTab(nextTab: Tab) {
    setTab(nextTab);
    if (nextTab === 'matches') void loadPublicData();
    if (nextTab === 'admin' || nextTab === 'contestants') void loadAdminData();
  }

  const topStanding = standings.slice(0, 3);
  const latestMatches = matches.slice(0, 5);
  const completedCount = matches.filter((match) => match.status === 'done').length;
  const activeCount = matches.filter((match) => match.status === 'running' || match.status === 'pending').length;
  const pageTitle: Record<Tab, string> = {
    overview: 'Tổng quan',
    matches: 'Trận đấu',
    live: 'Trung tâm trực tiếp',
    contestants: 'Thí sinh',
    admin: 'Ban tổ chức',
  };

  return (
    <div className="finals-app">
      <aside className="finals-sidebar">
        <a className="finals-brand" href="/" aria-label="OTT Finals">
          <span className="finals-brand-mark"><Swords size={21} /></span>
          <span><strong>OTT<span>FINALS</span></strong><small>ARENA CONTROL</small></span>
        </a>
        <div className="finals-nav-label">ĐẤU TRƯỜNG</div>
        <nav className="finals-nav">
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
            <button className={tab === id ? 'active' : ''} key={id} onClick={() => selectTab(id)}>
              <Icon size={18} strokeWidth={1.8} />
              <span>{label}</span>
              {id === 'live' && activeCount > 0 && <i className="finals-nav-live" />}
            </button>
          ))}
        </nav>
        <div className="finals-sidebar-bottom">
          <div className="finals-server-card">
            <span className="finals-server-light" />
            <div><strong>Hệ thống hoạt động</strong><small>Máy chủ chung kết</small></div>
          </div>
          <div className="finals-sidebar-user">
            <span className="finals-avatar">{user ? initials(user.display_name) : <UserRound size={16} />}</span>
            <div className="finals-sidebar-user-info">
              <strong>{user?.display_name ?? 'Khách xem'}</strong>
              <small>{user ? 'Thí sinh' : 'Chưa đăng nhập'}</small>
            </div>
            {user
              ? <button aria-label="Đăng xuất" className="finals-icon-button" onClick={() => void logout()}><LogOut size={16} /></button>
              : <button aria-label="Đăng nhập" className="finals-icon-button" onClick={() => selectTab('contestants')}><LogIn size={16} /></button>}
          </div>
        </div>
      </aside>

      <main className="finals-main">
        <header className="finals-topbar">
          <div className="finals-breadcrumb"><span>OTT FINALS</span><span className="finals-breadcrumb-sep">/</span><strong>{pageTitle[tab]}</strong></div>
          <div className="finals-topbar-actions">
            <span className="finals-live-indicator"><i /> HỆ THỐNG TRỰC TUYẾN</span>
            <button className="finals-icon-button finals-refresh" aria-label="Làm mới dữ liệu" onClick={() => void loadPublicData()}><RefreshCw size={17} /></button>
            <button className="finals-topbar-user" onClick={() => selectTab('contestants')}>
              <span className="finals-avatar">{user ? initials(user.display_name) : <UserRound size={16} />}</span>
              <span>{user?.display_name ?? 'Tài khoản'}</span>
              <ChevronDown size={15} />
            </button>
          </div>
        </header>

        {tab === 'overview' && (
          <section className="finals-content">
            <div className="finals-welcome">
              <div className="finals-welcome-copy">
                <div className="finals-eyebrow"><span /> MÙA GIẢI ĐANG DIỄN RA</div>
                <h1>Đường đến <em>ngôi vương.</em></h1>
                <p>Mọi diễn biến của vòng chung kết OTT — cập nhật theo thời gian thực.</p>
                <button className="finals-button finals-button-light" onClick={() => selectTab('matches')}>
                  Khám phá trận đấu <Swords size={16} />
                </button>
              </div>
              <div className="finals-trophy-art" aria-hidden="true">
                <span className="finals-orbit finals-orbit-one" />
                <span className="finals-orbit finals-orbit-two" />
                <span className="finals-trophy-glow" />
                <Trophy className="finals-trophy-icon" strokeWidth={1.1} />
                <span className="finals-art-star star-one">✦</span>
                <span className="finals-art-star star-two">✧</span>
                <span className="finals-art-star star-three">✦</span>
              </div>
              <div className="finals-welcome-index">01 <span>/ 04</span></div>
            </div>

            <div className="finals-stat-grid">
              <StatCard label="Thí sinh có điểm" value={standings.length} icon={<Users size={19} />} note="Trên bảng xếp hạng" />
              <StatCard label="Trận đã hoàn tất" value={completedCount} icon={<Check size={19} />} note="Kết quả đã được ghi nhận" />
              <StatCard label="Đang diễn ra" value={activeCount} icon={<Activity size={19} />} note={queue ? `${queue.queue_size} trận trong hàng chờ` : 'Trận đấu và hàng chờ'} accent />
              <StatCard label="Tổng trận đấu" value={matches.length} icon={<Swords size={19} />} note="50 trận gần nhất" />
            </div>

            <div className="finals-section-heading">
              <div><span className="finals-section-kicker">CUỘC ĐUA DANH HIỆU</span><h2>Bảng xếp hạng</h2></div>
              <button className="finals-text-button" onClick={() => selectTab('contestants')}>Xem toàn bộ <ArrowUpRight size={15} /></button>
            </div>
            <div className="finals-overview-grid">
              <section className="finals-panel finals-rank-panel">
                <div className="finals-panel-header"><div><Trophy size={17} /><strong>Top thí sinh</strong></div><span>ĐIỂM TÍCH LŨY</span></div>
                {topStanding.length === 0
                  ? <EmptyState title="Chưa có bảng xếp hạng" text="Kết quả sẽ xuất hiện sau trận đấu đầu tiên." />
                  : topStanding.map((standing, index) => (
                    <div className={`finals-rank-row rank-${index + 1}`} key={standing.username}>
                      <span className="finals-rank-number">{index === 0 ? <Crown size={17} /> : `0${index + 1}`}</span>
                      <span className={`finals-rank-avatar rank-avatar-${index + 1}`}>{initials(standing.username)}</span>
                      <div className="finals-rank-name"><strong>{standing.username}</strong><small>{standing.wins} thắng <span>·</span> {standing.draws} hòa <span>·</span> {standing.losses} thua</small></div>
                      <strong className="finals-rank-points">{standing.points}<small>đ</small></strong>
                    </div>
                  ))}
                <button className="finals-panel-footer" onClick={() => selectTab('contestants')}>Mở bảng xếp hạng đầy đủ <ArrowDownRight size={15} /></button>
              </section>
              <section className="finals-panel finals-recent-panel">
                <div className="finals-panel-header"><div><Clock3 size={17} /><strong>Trận đấu gần đây</strong></div><button className="finals-mini-link" onClick={() => selectTab('matches')}>Tất cả</button></div>
                {latestMatches.length === 0
                  ? <EmptyState title="Chưa có trận đấu nào" text="Các trận đấu mới sẽ được hiển thị tại đây." />
                  : latestMatches.map((match) => (
                    <button className="finals-recent-match" key={match.request_id} onClick={() => openMatch(match)}>
                      <span className="finals-match-id">#{String(match.id).padStart(3, '0')}</span>
                      <span className="finals-match-players"><strong>{match.player_a}</strong><small>vs</small><strong>{match.player_b}</strong></span>
                      <span className="finals-match-score">{match.status === 'done' ? `${match.score_a} – ${match.score_b}` : '— : —'}</span>
                      <StatusPill status={match.status} />
                    </button>
                  ))}
              </section>
            </div>
          </section>
        )}

        {tab === 'matches' && (
          <section className="finals-content">
            <PageHeading eyebrow="LỊCH SỬ ĐỐI ĐẦU" title="Tất cả trận đấu" description="Theo dõi kết quả, trạng thái và diễn biến của các cặp đấu." action={<button className="finals-button" onClick={() => selectTab('admin')}><Plus size={16} /> Tạo trận đấu</button>} />
            <div className="finals-stat-grid finals-match-stats">
              <StatCard label="Tổng số trận" value={matches.length} icon={<Swords size={19} />} />
              <StatCard label="Đã hoàn tất" value={completedCount} icon={<Check size={19} />} />
              <StatCard label="Đang xử lý" value={activeCount} icon={<Activity size={19} />} accent />
            </div>
            <div className="finals-panel finals-table-panel">
              <div className="finals-table-toolbar"><div><h2>Lịch sử trận đấu</h2><span>{matches.length} trận gần nhất</span></div><label className="finals-search"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Tìm thí sinh, mã trận..." /></label></div>
              <div className="finals-table-scroll"><table className="finals-table"><thead><tr><th>MÃ TRẬN</th><th>THÍ SINH</th><th>TỈ SỐ</th><th>KẾT QUẢ</th><th>TRẠNG THÁI</th><th>THỜI GIAN</th><th /></tr></thead>
                <tbody>{visibleMatches.map((match) => (
                  <tr key={match.request_id}>
                    <td><span className="finals-code">#{String(match.id).padStart(3, '0')}</span><small>{match.request_id.slice(0, 8)}</small></td>
                    <td><div className="finals-versus"><span>{match.player_a}</span><i>VS</i><span>{match.player_b}</span></div></td>
                    <td><strong className="finals-score">{match.status === 'done' ? `${match.score_a} – ${match.score_b}` : '— : —'}</strong></td>
                    <td>{match.winner ? <span className="finals-winner"><Medal size={14} /> {match.winner}</span> : match.status === 'done' ? <span className="finals-muted">Hòa</span> : '—'}</td>
                    <td><StatusPill status={match.status} /></td>
                    <td className="finals-muted">{formatDate(match.created_at, true)}</td>
                    <td><button className="finals-row-action" onClick={() => openMatch(match)} aria-label="Xem trận"><Eye size={16} /></button></td>
                  </tr>
                ))}</tbody>
              </table></div>
              {visibleMatches.length === 0 && <EmptyState title="Không tìm thấy trận đấu" text="Thử tìm bằng tên người chơi hoặc mã trận khác." />}
            </div>
          </section>
        )}

        {tab === 'live' && (
          <section className="finals-content">
            <PageHeading eyebrow="THEO DÕI DIỄN BIẾN" title="Trung tâm trực tiếp" description="Theo dõi từng nước đi hoặc xem lại những trận đã hoàn tất." />
            <div className="finals-live-toolbar">
              <label className="finals-select-wrap"><span>CHỌN TRẬN ĐẤU</span><select value={selectedId} onChange={(event) => {
                const match = matches.find((item) => item.request_id === event.target.value);
                if (match) openMatch(match);
              }}><option value="">Chọn một trận đấu...</option>{matches.map((match) => <option key={match.request_id} value={match.request_id}>#{match.id} · {match.player_a} vs {match.player_b} · {match.status}</option>)}</select><ChevronDown size={16} /></label>
              <label className="finals-select-wrap finals-game-select"><span>VÁN ĐẤU</span><select value={gameIndex} onChange={(event) => { setGameIndex(Number(event.target.value)); setStep(0); }}><option value={0}>Ván 1</option><option value={1}>Ván 2</option></select><ChevronDown size={16} /></label>
              {selectedMatch && <span className={`finals-live-badge ${live ? 'is-live' : ''}`}><i />{live ? 'ĐANG PHÁT' : selectedMatch.status === 'done' ? 'XEM LẠI' : selectedMatch.status === 'failed' ? 'TRẬN LỖI' : 'ĐANG CHỜ'}</span>}
            </div>
            {selectedMatch ? (
              <div className="finals-live-layout">
                <section className="finals-panel finals-board-panel">
                  <div className="finals-board-score">
                    <div><span className="finals-board-player player-a">{initials(selectedMatch.player_a)}</span><strong>{selectedMatch.player_a}</strong><small>THÍ SINH A</small></div>
                    <div className="finals-score-center"><strong>{selectedMatch.status === 'done' ? `${selectedMatch.score_a} : ${selectedMatch.score_b}` : 'VS'}</strong><span>VÁN {gameIndex + 1}</span></div>
                    <div><span className="finals-board-player player-b">{initials(selectedMatch.player_b)}</span><strong>{selectedMatch.player_b}</strong><small>THÍ SINH B</small></div>
                  </div>
                  {currentGame ? <Board pieces={boardPieces} lastMove={currentMoves[step - 1]?.[1] ?? null} /> : <div className="finals-board-placeholder"><Swords size={34} /><span>{selectedMatch.status === 'failed' ? selectedMatch.error_msg || 'Trận đấu thất bại.' : 'Đang chờ dữ liệu nước đi…'}</span></div>}
                  <div className="finals-replay-controls">
                    <button className="finals-row-action" onClick={() => { setPlaying(false); setStep(0); }} aria-label="Về đầu"><ArrowDownRight size={16} /></button>
                    <button className="finals-row-action" onClick={() => { setPlaying(false); setStep((value) => Math.max(0, value - 1)); }} aria-label="Lùi một nước">‹</button>
                    <button className="finals-play-button" onClick={() => {
                      if (live) return;
                      if (step >= currentMoves.length) setStep(0);
                      setPlaying((value) => !value);
                    }} disabled={live || currentMoves.length === 0}>{playing ? 'Tạm dừng' : <><Play size={15} fill="currentColor" /> Phát lại</>}</button>
                    <button className="finals-row-action" onClick={() => { setPlaying(false); setStep((value) => Math.min(currentMoves.length, value + 1)); }} aria-label="Tiến một nước">›</button>
                    <span className="finals-replay-step">{step} <i>/</i> {currentMoves.length} nước</span>
                  </div>
                  <input className="finals-progress" type="range" min={0} max={currentMoves.length} value={Math.min(step, currentMoves.length)} onChange={(event) => { setPlaying(false); setStep(Number(event.target.value)); }} aria-label="Tiến trình xem lại" />
                </section>
                <section className="finals-panel finals-feed-panel">
                  <div className="finals-panel-header"><div><Activity size={17} /><strong>Diễn biến trận đấu</strong></div><span className={live ? 'finals-feed-live' : 'finals-muted'}>{live ? 'LIVE' : `${feed.length} SỰ KIỆN`}</span></div>
                  <div className="finals-feed-list">{feed.length === 0 ? <EmptyState title="Chưa có diễn biến" text="Nước đi sẽ xuất hiện tại đây." /> : feed.slice().reverse().map((item, index) => <div className="finals-feed-item" key={`${item}-${index}`}><span className="finals-feed-dot" /><p>{item}</p></div>)}</div>
                  <div className="finals-feed-footer"><Radio size={14} /> Cập nhật trực tiếp qua kết nối an toàn</div>
                </section>
              </div>
            ) : <div className="finals-panel"><EmptyState title="Chọn trận để bắt đầu" text="Chọn một trận ở danh sách phía trên để xem trực tiếp hoặc phát lại." /></div>}
          </section>
        )}

        {tab === 'contestants' && (
          <section className="finals-content">
            <PageHeading eyebrow="CỘNG ĐỒNG ĐẤU TRƯỜNG" title="Thí sinh & xếp hạng" description="Bảng thành tích chung kết và thông tin tài khoản thí sinh." action={user ? <button className="finals-button finals-button-ghost" onClick={() => void logout()}><LogOut size={16} /> Đăng xuất</button> : undefined} />
            {!user && (
              <div className="finals-login-banner">
                <div className="finals-login-icon"><UserRound size={21} /></div>
                <div className="finals-login-copy"><strong>Đăng nhập tài khoản thí sinh</strong><span>Đăng nhập để xác nhận thông tin tham gia chung kết.</span></div>
                <form className="finals-login-form" onSubmit={(event) => void login(event)}>
                  <input required autoComplete="username" value={loginForm.username} onChange={(event) => setLoginForm((form) => ({ ...form, username: event.target.value }))} placeholder="Tên đăng nhập" />
                  <input required autoComplete="current-password" type="password" value={loginForm.password} onChange={(event) => setLoginForm((form) => ({ ...form, password: event.target.value }))} placeholder="Mật khẩu" />
                  <button className="finals-button" disabled={busy}><LogIn size={15} /> Đăng nhập</button>
                </form>
              </div>
            )}
            {user && <div className="finals-profile-card"><span className="finals-avatar finals-profile-avatar">{initials(user.display_name)}</span><div><small>ĐANG ĐĂNG NHẬP</small><strong>{user.display_name}</strong><span>{user.username} · MSSV {user.student_id || 'chưa cập nhật'}</span></div><button className="finals-row-action" onClick={() => void logout()} aria-label="Đăng xuất"><LogOut size={16} /></button></div>}
            <div className="finals-panel finals-table-panel">
              <div className="finals-table-toolbar"><div><h2>Bảng xếp hạng chung kết</h2><span>{standings.length} thí sinh có thành tích</span></div><button className="finals-button finals-button-ghost" onClick={() => void loadPublicData()}><RefreshCw size={15} /> Cập nhật</button></div>
              <div className="finals-table-scroll"><table className="finals-table"><thead><tr><th>HẠNG</th><th>THÍ SINH</th><th>THẮNG</th><th>HÒA</th><th>THUA</th><th>ĐIỂM</th><th>CẬP NHẬT</th></tr></thead><tbody>{standings.map((standing, index) => <tr key={standing.username}><td><span className={`finals-table-rank ${index < 3 ? `top-${index + 1}` : ''}`}>{index === 0 ? <Crown size={15} /> : `#${index + 1}`}</span></td><td><div className="finals-table-user"><span className={`finals-avatar rank-avatar-${Math.min(index + 1, 3)}`}>{initials(standing.username)}</span><strong>{standing.username}</strong></div></td><td className="finals-win">{standing.wins}</td><td>{standing.draws}</td><td className="finals-loss">{standing.losses}</td><td><strong className="finals-table-points">{standing.points}</strong></td><td className="finals-muted">{formatDate(standing.updated_at, true)}</td></tr>)}</tbody></table></div>
              {standings.length === 0 && <EmptyState title="Chưa có kết quả thi đấu" text="Bảng xếp hạng sẽ được cập nhật sau những trận đầu tiên." />}
            </div>
          </section>
        )}

        {tab === 'admin' && (
          <section className="finals-content">
            <PageHeading eyebrow="QUẢN LÝ ĐẤU TRƯỜNG" title="Bảng điều khiển BTC" description="Tạo trận, quản lý thí sinh và chốt bot cho vòng chung kết." />
            <section className="finals-panel finals-secret-panel">
              <span className="finals-secret-icon"><Shield size={20} /></span>
              <div className="finals-secret-copy"><strong>Kết nối quyền ban tổ chức</strong><span>Secret chỉ được lưu trong trình duyệt hiện tại.</span></div>
              <div className="finals-secret-input"><input aria-label="Admin secret" type={showAdminSecret ? 'text' : 'password'} value={adminSecret} onChange={(event) => setAdminSecret(event.target.value)} onBlur={() => adminSecret && localStorage.setItem(ADMIN_KEY, adminSecret)} placeholder="Nhập FINALS_ADMIN_SECRET" /><button aria-label={showAdminSecret ? 'Ẩn secret' : 'Hiện secret'} onClick={() => setShowAdminSecret((value) => !value)}>{showAdminSecret ? <EyeOff size={16} /> : <Eye size={16} />}</button></div>
              <button className="finals-button finals-button-ghost" onClick={() => { localStorage.setItem(ADMIN_KEY, adminSecret); void loadAdminData(); }}>Kết nối</button>
            </section>
            <div className="finals-admin-grid">
              <section className="finals-panel finals-form-panel">
                <div className="finals-panel-header"><div><Swords size={17} /><strong>Tạo trận đấu</strong></div><span className="finals-form-index">01</span></div>
                <p className="finals-form-intro">Chọn hai thí sinh đã đăng ký để đưa trận vào hàng đợi.</p>
                <form className="finals-form" onSubmit={(event) => void createMatch(event)}>
                  <div className="finals-form-grid"><label>Thí sinh A<input required value={matchForm.playerA} onChange={(event) => setMatchForm((form) => ({ ...form, playerA: event.target.value }))} placeholder="username_thi_sinh_a" /></label><span className="finals-form-vs">VS</span><label>Thí sinh B<input required value={matchForm.playerB} onChange={(event) => setMatchForm((form) => ({ ...form, playerB: event.target.value }))} placeholder="username_thi_sinh_b" /></label></div>
                  <label>Mã yêu cầu <small>KHÔNG BẮT BUỘC</small><input value={matchForm.requestId} onChange={(event) => setMatchForm((form) => ({ ...form, requestId: event.target.value }))} placeholder="Tự tạo nếu để trống" /></label>
                  <label>Tốc độ phát trực tiếp<select value={matchForm.liveDelay} onChange={(event) => setMatchForm((form) => ({ ...form, liveDelay: event.target.value }))}><option value="0.4">Tiêu chuẩn · 0,4 giây / nước</option><option value="0.2">Nhanh · 0,2 giây / nước</option><option value="0.8">Chậm · 0,8 giây / nước</option><option value="0">Tối đa tốc độ</option></select></label>
                  <label className="finals-checkbox"><input type="checkbox" checked={matchForm.autoLive} onChange={(event) => setMatchForm((form) => ({ ...form, autoLive: event.target.checked }))} /><span>Chuyển tới màn hình trực tiếp sau khi tạo trận</span></label>
                  <button className="finals-button finals-button-primary" disabled={busy || !adminSecret}><Radio size={16} /> {busy ? 'Đang tạo trận…' : 'Tạo trận đấu'}</button>
                </form>
              </section>
              <section className="finals-panel finals-form-panel">
                <div className="finals-panel-header"><div><UserRound size={17} /><strong>Thêm thí sinh</strong></div><span className="finals-form-index">02</span></div>
                <p className="finals-form-intro">Tạo tài khoản mới để thí sinh tham gia vòng chung kết.</p>
                <form className="finals-form" onSubmit={(event) => void addContestant(event)}>
                  <label>Tên đăng nhập<input required minLength={3} value={contestantForm.username} onChange={(event) => setContestantForm((form) => ({ ...form, username: event.target.value }))} placeholder="vd: nguyen_van_a" /></label>
                  <label>Họ và tên<input required value={contestantForm.displayName} onChange={(event) => setContestantForm((form) => ({ ...form, displayName: event.target.value }))} placeholder="Nguyễn Văn A" /></label>
                  <div className="finals-form-grid finals-form-grid-even"><label>Mật khẩu<input required minLength={6} type="password" autoComplete="new-password" value={contestantForm.password} onChange={(event) => setContestantForm((form) => ({ ...form, password: event.target.value }))} placeholder="Tối thiểu 6 ký tự" /></label><label>Mã sinh viên<input value={contestantForm.studentId} onChange={(event) => setContestantForm((form) => ({ ...form, studentId: event.target.value }))} placeholder="Không bắt buộc" /></label></div>
                  <button className="finals-button finals-button-primary" disabled={busy || !adminSecret}><Plus size={16} /> {busy ? 'Đang lưu…' : 'Thêm thí sinh'}</button>
                </form>
              </section>
            </div>
            <div className="finals-panel finals-table-panel">
              <div className="finals-table-toolbar"><div><h2>Danh sách thí sinh</h2><span>{contestants.length} tài khoản trong hệ thống</span></div><button className="finals-button finals-button-ghost" onClick={() => void loadAdminData()}><RefreshCw size={15} /> Làm mới</button></div>
              <div className="finals-table-scroll"><table className="finals-table"><thead><tr><th>THÍ SINH</th><th>HỌ VÀ TÊN</th><th>MÃ SINH VIÊN</th><th>NGÀY TẠO</th><th>BOT</th></tr></thead><tbody>{contestants.map((contestant) => <tr key={contestant.username}><td><div className="finals-table-user"><span className="finals-avatar">{initials(contestant.username)}</span><strong>{contestant.username}</strong></div></td><td>{contestant.display_name}</td><td className="finals-muted">{contestant.student_id || '—'}</td><td className="finals-muted">{formatDate(contestant.created_at)}</td><td><button className="finals-button finals-button-ghost finals-button-small" onClick={() => void snapshotBot(contestant.username)}><Check size={14} /> Chốt bot</button></td></tr>)}</tbody></table></div>
              {contestants.length === 0 && <EmptyState title={adminSecret ? 'Chưa có thí sinh nào' : 'Cần quyền ban tổ chức'} text={adminSecret ? 'Thêm tài khoản thí sinh bằng biểu mẫu phía trên.' : 'Nhập Admin Secret để xem danh sách và quản lý thí sinh.'} />}
            </div>
          </section>
        )}

        <footer className="finals-footer"><span>OTT FINALS <i>·</i> VÒNG CHUNG KẾT</span><span>Đấu hết mình. Vươn tới đỉnh cao. <Trophy size={13} /></span></footer>
      </main>
      {toast && <div className={`finals-toast ${toast.error ? 'is-error' : ''}`} role="status">{toast.error ? <CircleHelp size={17} /> : <Check size={17} />}{toast.message}<button aria-label="Đóng thông báo" onClick={() => setToast(null)}><X size={15} /></button></div>}
    </div>
  );
}

function StatCard({ label, value, icon, note, accent = false }: { label: string; value: string | number; icon: ReactNode; note?: string; accent?: boolean }) {
  return <div className={`finals-stat-card ${accent ? 'is-accent' : ''}`}><span className="finals-stat-icon">{icon}</span><span className="finals-stat-label">{label}</span><strong className="finals-stat-value">{value}</strong>{note && <span className="finals-stat-note">{note}</span>}</div>;
}

function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <div className="finals-page-heading"><div><span className="finals-section-kicker">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</div>;
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return <div className="finals-empty"><span><Bell size={18} /></span><strong>{title}</strong><p>{text}</p></div>;
}

function Board({ pieces, lastMove }: { pieces: Map<string, { icon: string; owner: 'a' | 'b' }>; lastMove: [number, number, number, number] | null }) {
  return (
    <div className="finals-board-frame">
      <div className="finals-board">
        {Array.from({ length: 9 }, (_, y) => Array.from({ length: 9 }, (_, x) => {
          const piece = pieces.get(`${x},${y}`);
          const isGoal = (x === 8 && y === 8) || (x === 0 && y === 0);
          const isLast = lastMove?.[2] === x && lastMove?.[3] === y;
          return <div className={`finals-square ${(x + y) % 2 ? 'is-dark' : ''} ${isGoal ? (x === 8 ? 'is-goal-a' : 'is-goal-b') : ''} ${isLast ? 'is-last' : ''}`} key={`${x}-${y}`} title={`${'abcdefghi'[x]}${y + 1}`}>
            {x === 0 && <span className="finals-coordinate coordinate-row">{y + 1}</span>}
            {y === 0 && <span className="finals-coordinate coordinate-column">{'abcdefghi'[x]}</span>}
            {isGoal && <span className="finals-goal">{x === 8 ? 'ĐÍCH A' : 'ĐÍCH B'}</span>}
            {piece && <span className={`finals-piece piece-${piece.owner}`}>{piece.icon}</span>}
          </div>;
        }))}
      </div>
      <div className="finals-board-legend"><span><i className="legend-a" />Thí sinh A · đi trước</span><span><i className="legend-b" />Thí sinh B · đi sau</span></div>
    </div>
  );
}

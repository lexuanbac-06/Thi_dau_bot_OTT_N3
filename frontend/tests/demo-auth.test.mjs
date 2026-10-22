import test from 'node:test';
import assert from 'node:assert/strict';
import { api, post, DEMO_ACCOUNT } from '../src/api.ts';
test('demo login, signup, duplicate validation, logout and upload', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => { throw new Error('Demo must not call backend'); };
  try {
    assert.equal((await api('/api/auth/session')).user, null);
    await assert.rejects(post('/api/auth/login', {}), /không đúng/);
    await assert.rejects(post('/api/auth/login', {name:'demo',password:'wrong'}), /không đúng/);
    assert.equal((await post('/api/auth/login',DEMO_ACCOUNT)).user.name,'demo');
    assert.equal((await api('/me')).name,'demo');
    assert.deepEqual(await api('/leaderboard'),[]);
    assert.deepEqual((await api('/replays')).matches,[]);
    const body=new FormData();body.append('file',new File(['print(1)'],'bot.py'));
    assert.equal((await api('/submit',{method:'POST',body})).demo,true);
    await post('/api/auth/logout',{});
    await assert.rejects(api('/me'), /đăng nhập/);
    await assert.rejects(post('/api/auth/register',{name:'demo',password:'newpassword'}), /sử dụng/);
    await assert.rejects(post('/api/auth/register',{name:'new_user',password:'short'}), /8–128/);
    assert.equal((await post('/api/auth/register',{name:'new_user',password:'newpassword'})).user.name,'new_user');
    await post('/api/auth/logout',{});
    assert.equal((await post('/api/auth/login',{name:'new_user',password:'newpassword'})).user.name,'new_user');
  } finally { globalThis.fetch=originalFetch; }
});

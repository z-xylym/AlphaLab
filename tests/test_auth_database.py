import uuid
from datetime import timedelta
import pytest
from sqlalchemy import select,update,text
from alphalab.config import UserError
from alphalab.db import users,sessions,private,now,metadata
from alphalab.auth import hasher
from alphalab.repository import Repository

@pytest.mark.parametrize('table',list(private))
def test_two_users_cannot_read_overwrite_delete_each_other(system,table):
    _,auth,a,b=system
    a.put(table,'same-id',{'owner':'A'})
    assert b.get(table,'same-id') is None
    b.put(table,'same-id',{'owner':'B'})
    assert a.get(table,'same-id')=={'owner':'A'}
    b.remove(table,'same-id')
    assert a.get(table,'same-id')=={'owner':'A'}
    b.remove(table)
    assert len(a.list(table))==1
    with pytest.raises(UserError):Repository(auth,'forged').list(table)

def test_bootstrap_invitation_password_and_role(system):
    s,auth,a,b=system
    assert not auth.bootstrap()
    with auth.db.connect() as c:
        user=c.execute(select(users).where(users.c.phone=='13800000002')).mappings().one()
        assert user['password_hash'].startswith('$argon2id$')
        assert hasher.verify(user['password_hash'],'test-user-password-strong')
    with pytest.raises(UserError):b.admin_users()
    with pytest.raises(UserError):auth.invite(b.token,'13800000003')
    with pytest.raises(UserError):auth.register('13800000003','long-enough-password','fake')
    code=auth.invite(a.token,'13800000003')
    auth.register('13800000003','long-enough-password',code)
    with pytest.raises(UserError):auth.register('13800000003','long-enough-password',code)

def test_rate_limit_and_session_revocation(system):
    _,auth,a,b=system
    for _ in range(5):
        with pytest.raises(UserError):auth.login('13800000002','bad')
    with pytest.raises(UserError,match='次数过多'):auth.login('13800000002','test-user-password-strong')
    auth.logout(b.token)
    with pytest.raises(UserError):b.list('chat_messages')

def test_expiry_disable_and_password_change(system):
    _,auth,a,b=system
    with auth.db.begin() as c:c.execute(update(sessions).where(sessions.c.token_hash==auth.digest(b.token)).values(expires_at=now()-timedelta(seconds=1)))
    with pytest.raises(UserError):b.get('user_memories','x')
    token=auth.login('13800000002','test-user-password-strong')
    auth.change_password(token,'test-user-password-strong','a-new-very-long-password')
    with pytest.raises(UserError):auth.current(token)
    token=auth.login('13800000002','a-new-very-long-password')
    user=auth.current(token)
    a.admin_update(user['id'],False,3)
    with pytest.raises(UserError):auth.current(token)

def test_private_memory_and_admin_metadata_only(system):
    _,_,a,b=system
    a.put('user_memories','a',{'secret':'A'})
    b.put('user_memories','b',{'secret':'B'})
    assert 'A' not in str(b.memory('secret'))
    assert 'B' not in str(a.memory('secret'))
    assert 'password_hash' not in str(a.admin_users())
    assert len(metadata.tables)>=24

def test_new_auth_instance_recovers_persistent_memory(system):
    settings,auth,a,b=system
    b.put('user_preferences','profile',{'level':'专业'})
    b.put('chat_messages','saved',{'role':'user','content':'持久化测试'})
    from alphalab.auth import Auth
    recovered=Repository(Auth(settings),b.token)
    assert recovered.get('user_preferences','profile')['level']=='专业'
    assert recovered.get('chat_messages','saved')['content']=='持久化测试'

def test_migration_cli_idempotent_and_browser_role_denied(system,monkeypatch):
    import os
    import subprocess
    import sys
    settings,auth,a,b=system
    env=os.environ.copy()
    env.update(DATABASE_URL=settings.database_url,APP_SECRET_KEY=settings.app_secret_key,
               ADMIN_PHONE=settings.admin_phone,ADMIN_INITIAL_PASSWORD=settings.admin_initial_password)
    for command in ('migrate','migrate','bootstrap','check'):
        result=subprocess.run([sys.executable,'-m','scripts.manage',command],env=env,capture_output=True,text=True)
        assert result.returncode==0,result.stdout
    # Supabase's browser role is not given a policy; even a mistaken SELECT grant cannot expose rows.
    b.put('chat_messages','rls-check',{'private':'B'})
    with auth.db.begin() as c:
        c.execute(text("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='alphalab_test_anon') THEN CREATE ROLE alphalab_test_anon NOLOGIN; END IF; END $$"))
        c.execute(text('GRANT USAGE ON SCHEMA public TO alphalab_test_anon'))
        c.execute(text('GRANT SELECT ON chat_messages TO alphalab_test_anon'))
        c.execute(text('SET LOCAL ROLE alphalab_test_anon'))
        assert c.scalar(text('SELECT count(*) FROM chat_messages'))==0

"""Real PostgreSQL-backed API integration; synthetic accounts only, no credentials in output."""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.request


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip('/')
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf = None
        self.csrf_user = None

    def clone(self):
        other = Client(self.base)
        for cookie in self.cookies:
            other.cookies.set_cookie(copy.copy(cookie))
        other.csrf = self.csrf
        other.csrf_user = self.csrf_user
        return other

    def request(self, method: str, route: str, body=None, csrf=True):
        headers = {'Accept': 'application/json'}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if method not in ('GET', 'HEAD') and csrf and self.csrf:
            headers['X-CSRF-TOKEN'] = self.csrf
        req = urllib.request.Request(self.base + route, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(req, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        raw = response.read().decode('utf-8')
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {'nonJsonResponse': True}
        return response.status, payload, dict(response.headers)

    def refresh_csrf(self):
        status, data, _ = self.request('GET', '/api/v1/auth/csrf')
        require(status == 200 and data.get('token'), 'CSRF token endpoint')
        require('userId' in data, 'CSRF token reports the bound identity')
        self.csrf = data['token']
        self.csrf_user = data['userId']


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def expect(status, allowed, label):
    require(status in (allowed if isinstance(allowed, tuple) else (allowed,)), f'{label}: expected {allowed}, received {status}')


def run_suite(base: str, output: Path):
    root = Path(__file__).resolve().parents[1]
    api = root / 'src' / 'Masar.Api' / 'bin' / 'Release' / 'net10.0' / 'Masar.Api.dll'
    suffix = secrets.token_hex(6)
    release = 'phase1-ar-v1'
    results = []
    # The randomly generated test credentials remain process-local and are never saved or printed.
    password = secrets.token_urlsafe(26)
    user_a = f'qa_a_{suffix}'
    user_b = f'qa_b_{suffix}'
    a, b, anonymous = Client(base), Client(base), Client(base)

    def check(name, action):
        started = time.monotonic()
        try:
            action()
            results.append({'name': name, 'status': 'PASSED', 'milliseconds': round((time.monotonic()-started)*1000)})
        except Exception as error:
            # Assertion errors contain only test labels and status codes, not requests/headers/credentials.
            results.append({'name': name, 'status': 'FAILED', 'reason': str(error) if isinstance(error, AssertionError) else type(error).__name__})
        print(f'{results[-1]["status"]}: {name}', flush=True)

    def health_and_catalog():
        expect(anonymous.request('GET', '/api/v1/health')[0], 200, 'database health')
        status, catalog, _ = anonymous.request('GET', '/api/v1/catalog')
        expect(status, 200, 'catalog')
        require(catalog['activeReleaseId'] == release, 'initial release is active')
        status, content, _ = anonymous.request('GET', f'/api/v1/content/{release}')
        expect(status, 200, 'published content')
        require(len(content['sample']['lessons']) == 3, 'three sample lessons')
        require('acceptedAnswers' not in json.dumps(content), 'answer keys absent from public content')
        expect(anonymous.request('GET', '/api/does-not-exist')[0], 404, 'unknown API is not SPA HTML')
    check('real database health, public content and answer-key filtering', health_and_catalog)

    def anonymous_and_csrf():
        expect(anonymous.request('GET', '/api/v1/auth/me')[0], 401, 'anonymous me')
        expect(anonymous.request('GET', '/api/v1/me/plan')[0], 401, 'anonymous plan')
        anonymous.refresh_csrf()
        require(anonymous.csrf_user is None, 'anonymous token has no bound account')
        status = anonymous.request('POST', '/api/v1/auth/register', {'userName':f'csrf_{suffix}','displayName':'اختبار مؤقت','password':password}, csrf=False)[0]
        expect(status, (400,403), 'missing csrf')
        expect(anonymous.request('GET', '/api/v1/auth/me')[0], 401, 'csrf failure did not sign in')
    check('anonymous access and CSRF fail closed', anonymous_and_csrf)

    def register_accounts():
        for client, name in [(a,user_a),(b,user_b)]:
            client.refresh_csrf()
            status, data, headers = client.request('POST','/api/v1/auth/register',{'userName':name,'displayName':'متعلم اختبار','password':password,'role':'Admin'})
            expect(status,201,'registration')
            require(data['user']['role']=='Learner','register cannot grant elevated role')
            session=next((cookie for cookie in client.cookies if cookie.name=='Masar.Session'),None)
            require(session is not None,'session cookie issued')
            flags={key.lower():value for key,value in session._rest.items()}
            require('httponly' in flags and str(flags.get('samesite')).lower()=='strict','session cookie has HttpOnly and SameSite=Strict')
            client.refresh_csrf()
            require(client.csrf_user==data['user']['id'],'authenticated CSRF token binds to that account')
            expect(client.request('GET','/api/v1/auth/me')[0],200,'authenticated me')
    check('two accounts, server sessions and fixed learner role', register_accounts)

    a_plan = {}
    def plan_revisions_and_ownership():
        status, preview, _ = a.request('POST','/api/v1/plan-previews',{'releaseId':release,'goalId':'explore','achievedSkillIds':['concept.program','concept.input-output','concept.sequence','concept.variable']})
        expect(status,200,'preview')
        require(len(preview['steps'])==3,'client cannot forge prior skill evidence')
        status, first, _ = a.request('POST','/api/v1/learning-plans',{'releaseId':release,'goalId':'explore'})
        expect(status,201,'first plan'); a_plan.update(first)
        expect(b.request('GET',f'/api/v1/learning-plans/{first["id"]}')[0],404,'cross-account plan')
        expect(a.request('POST','/api/v1/learning-plans',{'releaseId':release,'goalId':'web','expectedCurrentRevision':0})[0],409,'stale revision')
        status, second, _ = a.request('POST','/api/v1/learning-plans',{'releaseId':release,'goalId':'web','expectedCurrentRevision':first['revision']})
        expect(status,201,'plan revision')
        require(second['revision']==first['revision']+1,'revision increments')
        status, history, _ = a.request('GET','/api/v1/me/plan/history')
        expect(status,200,'history'); require(len(history['revisions'])==2,'both revisions retained')
        require(a.request('GET',f'/api/v1/learning-plans/{first["id"]}')[1]['goalId']=='explore','old plan remains unchanged')
    check('trusted previews, plan revisions, stale writes and resource ownership', plan_revisions_and_ownership)

    def drafts():
        route=f'/api/v1/me/drafts/{release}/program-output'
        status, saved, _=a.request('PUT',route,{'answer':'مسودة أولى','expectedVersion':0}); expect(status,200,'draft create')
        require(saved['version']==1,'draft version starts at one')
        expect(a.request('PUT',route,{'answer':'نسخة قديمة','expectedVersion':0})[0],409,'draft conflict')
        require(a.request('GET',route)[1]['answer']=='مسودة أولى','conflict preserves stored answer')
        expect(b.request('GET',route)[0],404,'draft private to owner')
        status,saved,_=a.request('PUT',route,{'answer':'مسودة معدلة','expectedVersion':1});expect(status,200,'draft update')
        require(saved['version']==2,'draft increments')
    check('server drafts, optimistic concurrency and account separation', drafts)

    def trusted_attempts():
        body={'releaseId':release,'lessonId':'what-is-a-program','exerciseId':'program-recognize','answer':'screen','hintsUsed':0,'idempotencyKey':f'wrong-{suffix}','correct':True,'achievedSkillIds':['concept.program']}
        status,wrong,_=a.request('POST','/api/v1/practice/attempts',body);expect(status,(200,201),'wrong attempt')
        require(wrong['correct'] is False,'server ignores claimed correctness')
        body['answer']='instructions';body['idempotencyKey']=f'correct-{suffix}';body['hintsUsed']=1
        status,correct,_=a.request('POST','/api/v1/practice/attempts',body);expect(status,(200,201),'correct attempt')
        require(correct['correct'] is True and correct['assisted'] is True,'assisted success remains practice')
        status,again,_=a.request('POST','/api/v1/practice/attempts',body);expect(status,(200,201),'idempotent retry')
        require(again['id']==correct['id'] and again['alreadyRecorded'] is True,'retry returns original evidence')
        body['answer']='screen'
        expect(a.request('POST','/api/v1/practice/attempts',body)[0],409,'idempotency payload conflict')
        status,p,_=a.request('GET',f'/api/v1/me/progress?releaseId={release}');expect(status,200,'progress')
        require(p['solved']==1 and p['attemptsCount']==2,'no repeated success counting')
        require(not any(skill['status']=='demonstrated' for skill in p['skills']),'phase two never fabricates mastery')
        require(b.request('GET',f'/api/v1/me/progress?releaseId={release}')[1]['solved']==0,'other account progress is empty')
    check('server grading, help tracking, idempotency and progress isolation', trusted_attempts)

    def complete_first_lesson_and_replan():
        for exercise,answer in [('program-output','أهلا سارة'),('program-library-transfer','pair')]:
            status,data,_=a.request('POST','/api/v1/practice/attempts',{'releaseId':release,'lessonId':'what-is-a-program','exerciseId':exercise,'answer':answer,'hintsUsed':0,'idempotencyKey':f'{exercise}-{suffix}'})
            expect(status,(200,201),'practice');require(data['correct'] is True,'accepted sample answer')
        p=a.request('GET',f'/api/v1/me/progress?releaseId={release}')[1]
        require('what-is-a-program' in p['completedLessonIds'] and len(p['practicedSkillIds'])==2,'lesson completion derives from stored attempts')
        status,p,_=a.request('POST','/api/v1/plan-previews',{'releaseId':release,'goalId':'python'});expect(status,200,'new goal preview')
        require(len(p['steps'])==2 and p['steps'][0]['lessonId']=='step-by-step','switching goal reuses practice without repeating first lesson')
    check('derived lesson completion and skill reuse when changing goal', complete_first_lesson_and_replan)

    def concurrent_idempotency():
        body={'releaseId':release,'lessonId':'step-by-step','exerciseId':'sequence-trace','answer':'٩','hintsUsed':0,'idempotencyKey':f'parallel-{suffix}'}
        clients=[a.clone() for _ in range(4)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            responses=list(pool.map(lambda client:client.request('POST','/api/v1/practice/attempts',body),clients))
        for status,data,_ in responses:
            expect(status,(200,201),'parallel attempt');require(data['correct'] is True,'Arabic numeral answer')
        require(len({data['id'] for _,data,_ in responses})==1,'concurrent deliveries create one evidence record')
    check('concurrent idempotent attempts and Arabic numerals', concurrent_idempotency)

    def content_workflow():
        expect(b.request('GET','/api/v1/admin/releases')[0],403,'learner cannot list drafts')
        # Explicit local administrative CLI used only for this synthetic test account.
        result=subprocess.run(['dotnet',str(api),'--promote-admin',user_a],cwd=api.parents[3],capture_output=True,env=os.environ.copy())
        require(result.returncode==0,'local CLI promotion')
        a.refresh_csrf()
        status,me,_=a.request('GET','/api/v1/auth/me');expect(status,200,'promoted me');require(me['user']['role']=='Admin','role re-read from database')
        sample=json.loads((root.parent/'phase1'/'content'/'sample.json').read_text(encoding='utf-8-sig'))
        graph=json.loads((root.parent/'phase1'/'content'/'graph.json').read_text(encoding='utf-8-sig'))
        next_release=f'qa-release-{suffix}';sample['releaseId']=next_release;graph['releaseId']=next_release
        status,created,_=a.request('POST','/api/v1/admin/releases',{'bundle':{'sample':sample,'graph':graph}});expect(status,201,'create draft')
        expect(b.request('GET',f'/api/v1/content/{next_release}')[0],404,'draft hidden from learner')
        content_id=created['id']
        expect(a.request('POST',f'/api/v1/admin/releases/{content_id}/activate',{'expectedVersion':1})[0],400,'draft cannot become default')
        expect(a.request('POST',f'/api/v1/admin/releases/{content_id}/transition',{'status':'published','expectedVersion':1})[0],(400,409),'cannot skip reviews')
        version=created.get('version',1)
        for status_name in ['technical_review','learning_review','published']:
            status,data,_=a.request('POST',f'/api/v1/admin/releases/{content_id}/transition',{'status':status_name,'expectedVersion':version})
            expect(status,200,f'transition {status_name}');version=data.get('version',version+1)
        expect(b.request('GET',f'/api/v1/content/{next_release}')[0],200,'published copy visible')
        current=a.request('GET','/api/v1/me/plan')[1]
        require(current['releaseId']==release,'publishing a new release does not migrate existing plan')
        expect(a.request('POST',f'/api/v1/admin/releases/{content_id}/transition',{'status':'retired','expectedVersion':1})[0],409,'stale content transition')
        status,history,_=a.request('GET','/api/v1/me/plan/history');expect(status,200,'plan history after new publication')
        require(len(history['revisions'])==2,'content publish leaves plan history intact')
        admin_status, admin_catalog,_=a.request('GET','/api/v1/admin/releases');expect(admin_status,200,'admin catalog')
        require(admin_catalog['activeReleaseId']==release,'publishing does not silently switch the default')
        initial=next(row for row in admin_catalog['releases'] if row['releaseId']==release)
        activate_path=f'/api/v1/admin/releases/{content_id}/activate'
        expect(b.request('POST',activate_path,{'expectedVersion':version})[0],403,'learner cannot change default')
        expect(a.request('POST',activate_path,{'expectedVersion':version-1})[0],409,'stale default selection')
        status,activated,_=a.request('POST',activate_path,{'expectedVersion':version});expect(status,200,'activate published release')
        require(activated['activeReleaseId']==next_release,'activation identifies the new default')
        catalog=b.request('GET','/api/v1/catalog')[1]
        require(catalog['activeReleaseId']==next_release and catalog['goals'],'public catalog follows explicit default')
        require(all(set(goal)=={'id','title','description','status','skillIds'} for goal in catalog['goals']),'catalog projects only public goal fields')
        require(a.request('GET','/api/v1/me/plan')[1]['releaseId']==release,'activation leaves existing plan pinned')
        status,_,_=a.request('POST',f'/api/v1/admin/releases/{content_id}/transition',{'status':'retired','expectedVersion':activated['version']});expect(status,200,'retire active release')
        catalog=b.request('GET','/api/v1/catalog')[1]
        require(catalog['activeReleaseId'] is None and any(row['releaseId']==release for row in catalog['releases']),'retiring default keeps available releases without silently selecting one')
        status,restored,_=a.request('POST',f'/api/v1/admin/releases/{initial["id"]}/activate',{'expectedVersion':initial['version']});expect(status,200,'explicitly restore initial default')
        require(restored['activeReleaseId']==release,'initial default restored without changing the plan')
    check('roles, content review workflow, optimistic versioning and pinned plans', content_workflow)

    def logout_revocation():
        replay=b.clone()
        expect(b.request('POST','/api/v1/auth/logout',{})[0],204,'logout')
        expect(replay.request('GET','/api/v1/auth/me')[0],401,'revoked cookie cannot be replayed')
        b.refresh_csrf()
        status,_,_=b.request('POST','/api/v1/auth/login',{'userName':user_b,'password':password});expect(status,200,'login after logout')
        b.refresh_csrf();expect(b.request('GET','/api/v1/auth/me')[0],200,'fresh session works')
    check('logout revokes stored session and a new login works', logout_revocation)

    def csrf_identity_switch():
        old_tab=a.clone()
        other_session=next(cookie for cookie in b.cookies if cookie.name=='Masar.Session')
        old_tab.cookies.set_cookie(copy.copy(other_session))
        route=f'/api/v1/me/drafts/{release}/sequence-trace'
        require(old_tab.csrf_user==a.csrf_user and a.csrf_user!=b.csrf_user,'separate account identity fixtures')
        status,_,_=old_tab.request('PUT',route,{'answer':'مسودة من الحساب السابق','expectedVersion':0})
        expect(status,400,'old CSRF token cannot write after session cookie changes')
        old_tab.refresh_csrf()
        require(old_tab.csrf_user==b.csrf_user,'new token exposes the changed account to the UI')
        expect(b.request('GET',route)[0],404,'old draft was not saved to the new account')
    check('CSRF account binding blocks an old tab after changing the session', csrf_identity_switch)

    def persistence_and_login_lock():
        child_env=os.environ.copy()
        child_env.pop('ConnectionStrings__Migration',None)
        child_env['ASPNETCORE_URLS']='http://127.0.0.1:5182'
        process=None
        client=Client('http://127.0.0.1:5182')
        def start_owned_server():
            owned=subprocess.Popen(['dotnet',str(api)],cwd=api.parents[3],env=child_env,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            for _ in range(80):
                if owned.poll() is not None:
                    raise AssertionError('owned restart-test server stopped before readiness')
                try:
                    if client.request('GET','/api/v1/health')[0]==200:
                        return owned
                except urllib.error.URLError:
                    pass
                time.sleep(0.1)
            owned.terminate();owned.wait(timeout=10)
            raise AssertionError('owned restart-test server readiness timeout')
        try:
            process=start_owned_server()
            name=f'qa_restart_{suffix}'
            client.refresh_csrf()
            expect(client.request('POST','/api/v1/auth/register',{'userName':name,'displayName':'تجربة الاستعادة','password':password})[0],201,'restart account')
            client.refresh_csrf()
            status,saved_plan,_=client.request('POST','/api/v1/learning-plans',{'releaseId':release,'goalId':'explore'});expect(status,201,'restart plan')
            draft_route=f'/api/v1/me/drafts/{release}/program-output'
            expect(client.request('PUT',draft_route,{'answer':'نص يبقى بعد إعادة التشغيل','expectedVersion':0})[0],200,'restart draft')
            process.terminate();process.wait(timeout=10);process=None
            process=start_owned_server()
            expect(client.request('GET','/api/v1/auth/me')[0],200,'session survives owned process restart')
            restored_plan=client.request('GET','/api/v1/me/plan')[1]
            require(restored_plan['id']==saved_plan['id'],'plan persists after server restart')
            require(client.request('GET',draft_route)[1]['answer']=='نص يبقى بعد إعادة التشغيل','draft persists after server restart')
            # Use the pre-restart anti-forgery token to verify persistent protected key storage.
            expect(client.request('PUT',draft_route,{'answer':'نص بعد الاستعادة','expectedVersion':1})[0],200,'CSRF token validates after key-ring reload')
            for _ in range(5):
                expect(client.request('POST','/api/v1/auth/login',{'userName':name,'password':secrets.token_urlsafe(25)})[0],401,'failed login')
            expect(client.request('POST','/api/v1/auth/login',{'userName':name,'password':password})[0],401,'persisted login lock blocks correct password')
        finally:
            if process is not None:
                process.terminate();process.wait(timeout=10)
    check('process restart preserves session, CSRF keys, plan and draft; login lock is enforced', persistence_and_login_lock)

    def invalid_release_and_role_boundaries():
        expect(b.request('POST','/api/v1/admin/releases',{'bundle':{}})[0],403,'learner cannot author')
        status,data,_=a.request('POST','/api/v1/admin/releases',{'bundle':{'sample':{},'graph':{}}})
        expect(status,400,'invalid curriculum is rejected')
        expect(a.request('POST','/api/v1/plan-previews',{'releaseId':release,'goalId':'missing'})[0],404,'unknown goal is not fabricated')
        status,planned,_=anonymous.request('POST','/api/v1/plan-previews',{'releaseId':release,'goalId':'react'})
        expect(status,200,'planned preview');require(planned['status']=='planned' and planned['uncoveredSkillIds'],'planned goal exposes coverage gap')
        sample=json.loads((root.parent/'phase1'/'content'/'sample.json').read_text(encoding='utf-8-sig'))
        graph=json.loads((root.parent/'phase1'/'content'/'graph.json').read_text(encoding='utf-8-sig'))
        for name, mutate in [
            ('missing-objectives',lambda doc:doc['lessons'][0].pop('objectives')),
            ('null-sections',lambda doc:doc['lessons'][0].update(sections=None)),
            ('missing-glossary',lambda doc:doc.pop('glossary')),
            ('invalid-example',lambda doc:doc['lessons'][0].update(examples=[{'title':'ناقص'}]))
        ]:
            bad_sample=copy.deepcopy(sample);bad_graph=copy.deepcopy(graph)
            bad_id=f'qa-{name}-{suffix}';bad_sample['releaseId']=bad_id;bad_graph['releaseId']=bad_id
            mutate(bad_sample)
            expect(a.request('POST','/api/v1/admin/releases',{'bundle':{'sample':bad_sample,'graph':bad_graph}})[0],400,f'reject {name}')
    check('authoring roles, invalid curriculum rejection and unavailable goal coverage', invalid_release_and_role_boundaries)

    report={'suite':'masar-phase2-real-postgresql-http','scope':'dedicated local test database; synthetic accounts only','passed':sum(r['status']=='PASSED' for r in results),'failed':sum(r['status']=='FAILED' for r in results),'tests':results}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:report[key] for key in ['suite','passed','failed']},ensure_ascii=False))
    return 0 if report['failed']==0 else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',default='http://127.0.0.1:5181')
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'test-results'/'http-integration.json')
    args=parser.parse_args()
    if args.base.rstrip('/') != 'http://127.0.0.1:5181':
        raise SystemExit('Only a dedicated local test server is permitted.')
    raise SystemExit(run_suite(args.base,args.output))

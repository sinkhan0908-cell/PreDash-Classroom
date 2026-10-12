"""Use complete session credentials or complete Secrets, never mix sources."""
import os
import streamlit as st
from predash.kis import KIS, BrokerError


FIELDS = ('key', 'secret', 'cano', 'product')


def resolve_settings(session, secrets, mode=None):
    selected = mode or (session.get('mode') if all(session.get(k) for k in FIELDS) else None) or str(secrets.get('KIS_ENV', 'demo')).strip()
    empty = dict(mode=selected, **{k: '' for k in FIELDS})
    if session.get('mode') == selected and all(session.get(k) for k in FIELDS):
        return dict(mode=selected, **{k: str(session[k]).strip() for k in FIELDS})
    stored_mode = str(secrets.get('KIS_ENV', 'demo')).strip()
    prefix = 'KIS_'
    if selected == 'demo' and (stored_mode != 'demo' or any(secrets.get('KIS_DEMO_' + k) for k in ('APP_KEY', 'APP_SECRET', 'CANO', 'ACNT_PRDT_CD'))):
        prefix = 'KIS_DEMO_'
    elif selected != stored_mode:
        return empty
    candidate = dict(mode=selected, **{k: str(secrets.get(prefix + suffix, '')).strip()
                                      for k, suffix in zip(FIELDS, ('APP_KEY', 'APP_SECRET', 'CANO', 'ACNT_PRDT_CD'))})
    return candidate if all(candidate[k] for k in FIELDS) else empty


def account_settings(mode=None):
    if st.session_state.get('classroom_kis_disabled'):
        return dict(mode=mode or 'demo', **{k: '' for k in FIELDS})
    try:
        secrets = dict(st.secrets)
    except (FileNotFoundError, KeyError):
        secrets = {}
    for k in ('KIS_ENV', 'KIS_APP_KEY', 'KIS_APP_SECRET', 'KIS_CANO', 'KIS_ACNT_PRDT_CD',
              'KIS_DEMO_APP_KEY', 'KIS_DEMO_APP_SECRET', 'KIS_DEMO_CANO', 'KIS_DEMO_ACNT_PRDT_CD'):
        if k not in secrets and os.getenv(k):
            secrets[k] = os.getenv(k)
    return resolve_settings(st.session_state.get('classroom_credentials', {}), secrets, mode)


def connection_form():
    if st.session_state.pop('classroom_clear_inputs', False):
        for key in ('class_key','class_secret','class_cano','class_product'):
            st.session_state.pop(key, None)
    st.subheader('내 증권사 계좌 연결')
    st.caption('화면 입력 또는 Streamlit Secrets 중 한 곳에 키·계좌를 모두 설정하면 됩니다. 화면에서 연결한 값을 우선 사용합니다.')
    if st.session_state.get('classroom_credentials'):
        st.success('계좌 연결됨 · ' + ('모의투자' if account_settings()['mode']=='demo' else '실전 조회'))
        if st.button('계좌 연결 해제'):
            authorized = st.session_state.get('authorized')
            st.session_state.clear()
            st.session_state.classroom_kis_disabled = True
            if authorized: st.session_state.authorized = True
            st.rerun()
        return
    configured = account_settings()
    if all(configured[k] for k in FIELDS):
        st.info('Streamlit Secrets 설정됨 · ' + ('모의투자' if configured['mode']=='demo' else '실전 조회') + ' · 실제 연결은 아래 버튼으로 확인하세요.')
        if st.button('Secrets로 연결 확인', type='primary'):
            try:
                client = KIS(settings=configured)
                with st.spinner('잔고 조회 권한을 확인합니다…'):
                    client.balance()
                st.session_state['_kis_client_demo' if configured['mode']=='demo' else '_kis_client'] = client
                st.success('Secrets 인증·잔고 조회 성공')
            except BrokerError as error:
                st.error(str(error))
    elif st.session_state.get('classroom_kis_disabled'):
        if st.button('Secrets 설정 다시 사용'):
            st.session_state.pop('classroom_kis_disabled', None)
            st.rerun()
    with st.form('classroom_connection'):
        mode = st.radio('투자 환경', ['모의투자','실전 조회'], horizontal=True)
        key = st.text_input('App Key', type='password', key='class_key')
        secret = st.text_input('App Secret', type='password', key='class_secret')
        cano = st.text_input('계좌번호 앞 8자리', type='password', max_chars=8, key='class_cano')
        product = st.text_input('계좌번호 뒤 2자리', max_chars=2, key='class_product')
        submitted = st.form_submit_button('연결 확인', type='primary', use_container_width=True)
    if submitted:
        settings = dict(mode='demo' if mode=='모의투자' else 'real',key=key.strip(),secret=secret.strip(),cano=cano.strip(),product=product.strip())
        try:
            client = KIS(settings=settings)
            with st.spinner('잔고 조회 권한을 확인합니다…'):
                client.balance()
            st.session_state.classroom_credentials = settings
            st.session_state.pop('classroom_kis_disabled', None)
            st.session_state['_kis_client_demo' if settings['mode']=='demo' else '_kis_client'] = client
            st.session_state.classroom_clear_inputs = True
            st.rerun()
        except BrokerError as error:
            st.error(str(error))
    st.info('화면 입력은 세션에서만 보관됩니다. 로그아웃은 화면 입력을 지우며, Streamlit Secrets에 저장된 값은 유지됩니다.')

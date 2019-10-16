#
# File: wxapp.py
# Copyright: Grimm Project, Ren Pin NGO, all rights reserved.
# License: MIT
# -------------------------------------------------------------------------
# Authors:  Ming Li(adagio.ming@gmail.com)
#
# Description: all view functions for wxapp,
#
# To-Dos:
#   1. make other supplements if needed.
#
# Issues:
#   No issue so far.
#
# Revision History (Date, Editor, Description):
#   1. 2019/09/19, Ming, create first revision.
#

import sys
import os
import time
from datetime import datetime
import json
from flask import request, url_for
import urllib3

import server.core.db as db
import server.utils.sms_verify as sms_verify
from server.core import grimm as app
from server.core import wxappid, wxsecret
from server import user_logger


SMS_VRF_EXPIRY = 300


@app.route('/jscode2session')
def wxjscode2session():
    '''view function for validating weixin user openid'''
    js_code = request.args.get("js_code")
    prefix = 'https://api.weixin.qq.com/sns/jscode2session?appid='
    suffix = '&grant_type=authorization_code'
    url = prefix + wxappid + '&secret=' + wxsecret + '&js_code=' + js_code + suffix
    user_logger.info('user login, wxapp authorization: %s', url)
    http = urllib3.PoolManager()
    response = http.request('GET', url)
    # authorization success
    if response.status == 200:
        feedback = json.loads(response.data)
        feedback['server_errcode'] = 0
        openid = feedback['openid']
        # query user in database
        try:
            info = db.expr_query('user', openid=openid)
        except:
            return json.dumps({'status': 'failure', 'message': '未知错误'}, encoding='utf8')
        if info:
            feedback['is_register'] = False
            if info['approval_status'] == 0:
                feedback['approval_status'] = 'proceeding'
            elif info['approval_status'] == 1:
                feedback['approval_status'] = 'approved'
            else:
                feedback['approval_status'] = 'rejected'
        else:
            feedback['is_register'] = True
        feedback['status'] = 'success'
        user_logger.info('%s: wxapp authorization success', openid)
    else:
        user_logger.error('%s: wxapp authorization failed', openid)
        feedback['status'] = 'failure'

    return json.dumps(feedback, encoding='utf8')


@app.route('/register', methods=['POST'])
def register():
    '''view function for registering new user to database'''
    if request.method == 'POST':
        userinfo = feedback = {}
        info = json.loads(request.get_data().decode('utf8'))  # get http POST data bytes format
        # fetch data from front end
        userinfo['openid'] = request.headers.get('Authorization')
        if not db.exist_row('user', openid=userinfo['openid']):
            userinfo['birth'] = info['birthdate']
            userinfo['remark'] = info['comment']
            userinfo['disabled_id'] = info['disabledID']
            userinfo['emergent_contact'] = info['emergencyPerson']
            userinfo['emergent_contact_phone'] = info['emergencyTel']
            userinfo['gender'] = info['gender']
            userinfo['idcard'] = info['idcard']
            userinfo['address'] = info['linkaddress']
            userinfo['contact'] = info['linktel']
            userinfo['phone'] = info['tel']
            userinfo['name'] = info['name']
            userinfo['role'] = 0 if info['role'] == "志愿者" else 1

            # add extra info
            userinfo['registration_date'] = datetime.now().strftime('%Y-%m-%d')
            try:
                if db.expr_insert('user', userinfo) != 1:
                    user_logger.error('%s: user register failed', userinfo['openid'])
                    return json.dumps({'status': 'failure', 'message': '录入用户失败'}, encoding='utf8')
            except:
                user_logger.error('%s: user register failed', userinfo['openid'])
                return json.dumps({'status': 'failure', 'message': '注册失败，请重新注册'}, encoding='utf8')
            user_logger.info('%s: user register success', userinfo['openid'])
            return json.dumps({'status': 'success'}, encoding='utf8')

        feedback['status'] = 'failure'
        feedback['message'] = '用户已注册'
        return json.dumps(feedback, encoding='utf8')


@app.route('/profile', methods=['POST', 'GET'])
def profile():
    '''view function for displaying or updating user profile'''
    feedback = {'status': 'success'}
    if request.method == 'GET':
        openid = request.headers.get('Authorization')
        if db.exist_row('user', openid=openid):
            try:
                userinfo = db.expr_query('user', openid=openid)
            except:
                return json.dumps({'status': 'failure', 'message': '未知错误'}, encoding='utf8')
            feedback['openid'] = userinfo['openid']
            feedback['birthDate'] = userinfo['birth']
            feedback['usercomment'] = userinfo['remark']
            feedback['disabledID'] = userinfo['disabled_id']
            feedback['emergencyPerson'] = userinfo['emergent_contact']
            feedback['emergencyTel'] = userinfo['emergent_contact_phone']
            feedback['gender'] = userinfo['gender']
            feedback['idcard'] = userinfo['idcard']
            feedback['linkaddress'] = userinfo['address']
            feedback['linktel'] = userinfo['contact']
            feedback['name'] = userinfo['name']
            feedback['role'] = "志愿者" if userinfo['role'] == 0 else "视障人士"
            feedback['tel'] = userinfo['phone']

            return json.dumps(feedback, encoding='utf8')

        feedback['status'] = 'failure'
        feedback['message'] = "未注册用户"
        return json.dumps(feedback, encoding='utf8')

    if request.method == 'POST':
        newinfo = json.loads(request.get_data().decode('utf8'))  # get request POST user data
        userinfo = {}
        userinfo['phone'] = newinfo['tel']
        userinfo['gender'] = newinfo['gender']
        userinfo['birth'] = newinfo['birthDate']
        userinfo['contact'] = newinfo['linktel']
        userinfo['address'] = newinfo['linkaddress']
        userinfo['emergent_contact'] = newinfo['emergencyPerson']
        userinfo['emergent_contact_phone'] = newinfo['emergencyTel']
        userinfo['remark'] = newinfo['usercomment']
        userinfo['openid'] = newinfo['openid']

        try:
            if db.expr_update('user', userinfo, openid=userinfo['openid']) != 1:
                user_logger.error('%s: user update info failed', userinfo['openid'])
                return json.dumps({'status': 'failure', 'message': "更新失败，请重新输入"}, encoding='utf8')
        except:
            return json.dumps({'status': 'failure', 'message': '未知错误'}, encoding='utf8')

        user_logger.info('%s: user update info successfully', userinfo['openid'])
        return json.dumps({'status': 'success'}, encoding='utf8')


@app.route('/send-smscode', methods=['GET'])
def send_smscode():
    '''view function to send sms verification code to new user'''
    if request.method == 'GET':
        info = json.loads(request.get_data().decode('utf8'))
        sms_verify.drop_token(info['tel'])  # drop old token if it exists
        try:
            token = sms_verify.SMSVerifyToken(phone_number=info['tel'],
                                              expiry=SMS_VRF_EXPIRY,
                                              template_code=sms_verify.TEMPLATE_CODES['REGISTER_USER'])
            token.send_sms()
        except Exception as err:
            return json.dumps({'status': 'failure', 'message': err.args[1]}, encoding='utf8')
        sms_verify.append_token(token)

        return json.dumps({'status': 'success'}, encoding='utf8')


@app.route('confirm-smscode', methods=['GET'])
def confirm_smscode():
    '''view function to confirm sms verification code'''
    if request.method == 'GET':
        info = json.loads(request.get_data().decode('utf8'))
        token = sms_verify.fetch_token(info['tel'])
        if token is None:
            return json.dumps({'status': 'failure', 'message': '未向该用户发送验证短信'}, encoding='utf8')
        if not token.validate(phone_number=token.phone_number, vrfcode=info['vrfcode']):
            return json.dumps({'status': 'failure', 'message': '验证未通过' }, encoding='utf8')
        return json.dumps({'status': 'success'}, encoding='utf8')

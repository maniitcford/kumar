import time
import transaction
import ZODB.POSException

from pyramid_zodbconn import get_connection
from pyramid.httpexceptions import HTTPFound
from pyramid.view import view_defaults
from pyramid.security import unauthenticated_userid

from .. import mgmt_view
from ...objectmap import find_objectmap

@view_defaults(
    physical_path='/',
    permission='sdi.undo'
    )
class UndoViews(object):
    transaction = transaction # for tests
    get_connection = staticmethod(get_connection) # for tests
    find_objectmap = staticmethod(find_objectmap) # for tests
    unauthenticated_userid = staticmethod(unauthenticated_userid) # for tests

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def _get_db(self):
        request = self.request
        conn = self.get_connection(request)
        db = conn.db()
        return db

    @mgmt_view(
        name='undo_one',
        tab_condition=False, 
        check_csrf=True
        )
    def undo_one(self):
        request = self.request
        undohash = request.params['undohash']
        undo = None
        db = self._get_db()
        for record in db.undoLog(0, -50):
            # the last 50 transactions
            if record.get('undohash') == undohash:
                undo = dict(record)
                break
        if undo is None:
            request.session.flash('Could not undo, sorry', 'error')
        else:
            tid = undo['id']
            try:
                db.undo(tid)
                # provoke MultipleUndoErrors exception immediately
                msg = 'Undid: %s' % undo['description']
                self.transaction.get().note(msg)
                self.transaction.commit() 
                request.session.flash(msg, 'success')
            except ZODB.POSException.POSError:
                self.transaction.abort()
                msg = 'Could not undo, sorry'
                request.session.flash(msg, 'error')
        return HTTPFound(
            request.referrer or request.sdiapi.mgmt_path(request.context)
            )

    @mgmt_view(
        name='undo_multiple',
        tab_condition=False, 
        check_csrf=True,
        )
    def undo_multiple(self):
        request = self.request

        transaction_info = self.request.POST.getall('transaction')

        tids = []
        descriptions = []

        uid = self.unauthenticated_userid(request)

        for tid in transaction_info:
            tid = tid.split(' ', 1)
            if tid:
                tids.append(decode64(tid[0]))
                descriptions.append(tid[1])

        if tids:
            undid = "Undid: %s" % ' '.join(descriptions)
            t = self.transaction.get()
            t.note(undid)
            t.setUser(uid)
            try:
                self._get_db().undoMultiple(tids)
                # provoke MultipleUndoErrors exception immediately
                self.transaction.commit() 
                request.session.flash(undid, 'success')
            except ZODB.POSException.POSError:
                self.transaction.abort()
                msg = 'Could not undo, sorry'
                request.session.flash(msg, 'error')

        return HTTPFound(request.sdiapi.mgmt_path(request.context, 'undo'))

    def _undoable_transactions(self, first, last):
        db = self._get_db()

        objectmap = self.find_objectmap(self.context)

        r = db.undoLog(first, last)

        for d in r:
            d['time'] = time.ctime(d['time'])[4:][:-5]
            desc = d['description'] or ''
            tid = d['id']
            un = d['user_name']
            try:
                un = objectmap.object_for(int(un.split()[-1].strip()))
                d['user_name'] = un.__name__
            except: # use original username if any trouble
                pass
            if len(desc) > 80:
                desc = desc[:76] + ' ...'
            tid = "%s %s" % (encode64(tid), desc)
            d['id'] = tid

        return r

    @mgmt_view(
        name='undo',
        tab_title='Undo',
        renderer='templates/undo.pt',
        )
    def undo(self):
        first = int(self.request.GET.get('first', 0))
        size = 10
        last = first + size

        batch = self._undoable_transactions(first, last)

        if len(batch) < size:
            earlier = None
        else:
            earlier = last
            earlier = self.request.sdiapi.mgmt_path(
                self.context, 'undo', _query={'first':earlier}
                )
        if first <= 0:
            later = None
        else:
            later = first - size
            later = self.request.sdiapi.mgmt_path(
                self.context, 'undo', _query={'first':later}
                )

        batch_num = first / size
        
        return {'batch':batch, 'earlier':earlier, 'later':later,
                'batch_num':batch_num}
        
        
            
########################################################################
# Blech, need this cause binascii.b2a_base64 is too picky (from Zope)

import binascii

def encode64(s, b2a=binascii.b2a_base64):
    if len(s) < 58:
        return b2a(s)
    r = []
    a = r.append
    for i in range(0, len(s), 57):
        a(b2a(s[i:i+57])[:-1])
    return ''.join(r)


def decode64(s, a2b=binascii.a2b_base64):
    return a2b(s+'\n')

del binascii

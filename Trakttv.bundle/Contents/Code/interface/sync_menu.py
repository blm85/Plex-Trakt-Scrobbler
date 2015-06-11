from core.helpers import timestamp, pad_title, function_path, redirect
from core.localization import localization
from core.logger import Logger

from plugin.core.constants import PLUGIN_PREFIX
from plugin.core.filters import Filters
from plugin.core.helpers.variable import normalize
from plugin.managers import AccountManager
from plugin.models import Account, SyncResult
from plugin.sync import Sync, SyncData, SyncMedia, SyncMode, QueueError

from ago import human
from datetime import datetime
from plex import Plex

L, LF = localization('interface.sync_menu')

log = Logger('interface.sync_menu')


# NOTE: pad_title(...) is used to force the UI to use 'media-details-list'

@route(PLUGIN_PREFIX + '/sync/accounts')
def AccountsMenu(refresh=None):
    oc = ObjectContainer(
        title2=L('accounts:title'),
        no_cache=True
    )

    # Active sync status
    Active.create(
        oc,
        callback=Callback(AccountsMenu, refresh=timestamp()),
    )

    # Accounts
    for account in AccountManager.get.all():
        oc.add(DirectoryObject(
            key=Callback(ControlsMenu, account_id=account.id),
            title=account.name,

            art=function_path('Cover.png', account_id=account.id),
            thumb=function_path('Thumb.png', account_id=account.id)
        ))

    return oc


@route(PLUGIN_PREFIX + '/sync')
def ControlsMenu(account_id=1, title=None, message=None, refresh=None):
    account = AccountManager.get(Account.id == account_id)

    # Build sync controls menu
    oc = ObjectContainer(
        title2=LF('controls:title', account.name),
        no_cache=True,

        art=function_path('Cover.png', account_id=account.id)
    )

    # Start result message
    if title and message:
        oc.add(DirectoryObject(
            key=Callback(ControlsMenu, account_id=account.id, refresh=timestamp()),
            title=pad_title(title),
            summary=message
        ))

    # Active sync status
    Active.create(
        oc,
        callback=Callback(ControlsMenu, account_id=account.id, refresh=timestamp()),
        account=account
    )

    #
    # Full
    #

    oc.add(DirectoryObject(
        key=Callback(Synchronize, account_id=account.id, refresh=timestamp()),
        title=pad_title(SyncMode.title(SyncMode.Full)),
        summary=Status.build(account, SyncMode.Full),

        thumb=R("icon-sync.png"),
        art=function_path('Cover.png', account_id=account.id)
    ))

    #
    # Pull
    #

    oc.add(DirectoryObject(
        key=Callback(Pull, account_id=account.id, refresh=timestamp()),
        title=pad_title('%s from trakt' % SyncMode.title(SyncMode.Pull)),
        summary=Status.build(account, SyncMode.Pull),

        thumb=R("icon-sync_down.png"),
        art=function_path('Cover.png', account_id=account.id)
    ))

    oc.add(DirectoryObject(
        key=Callback(FastPull, account_id=account.id, refresh=timestamp()),
        title=pad_title('%s from trakt' % SyncMode.title(SyncMode.FastPull)),
        summary=Status.build(account, SyncMode.FastPull),

        thumb=R("icon-sync_down.png"),
        art=function_path('Cover.png', account_id=account.id)
    ))

    #
    # Push
    #

    sections = Plex['library'].sections()
    section_keys = []

    f_allow, f_deny = Filters.get('filter_sections')

    for section in sections.filter(['show', 'movie'], titles=f_allow):
        oc.add(DirectoryObject(
            key=Callback(Push, account_id=account.id, section=section.key, refresh=timestamp()),
            title=pad_title('%s "%s" to trakt' % (SyncMode.title(SyncMode.Push), section.title)),
            summary=Status.build(account, SyncMode.Push, section.key),

            thumb=R("icon-sync_up.png"),
            art=function_path('Cover.png', account_id=account.id)
        ))
        section_keys.append(section.key)

    if len(section_keys) > 1:
        oc.add(DirectoryObject(
            key=Callback(Push, account_id=account.id, refresh=timestamp()),
            title=pad_title('%s all to trakt' % SyncMode.title(SyncMode.Push)),
            summary=Status.build(account, SyncMode.Push),

            thumb=R("icon-sync_up.png"),
            art=function_path('Cover.png', account_id=account.id)
        ))

    return oc


@route(PLUGIN_PREFIX + '/sync/synchronize')
def Synchronize(account_id=1, refresh=None):
    return Trigger(int(account_id), SyncMode.Full)


@route(PLUGIN_PREFIX + '/sync/fast_pull')
def FastPull(account_id=1, refresh=None):
    return Trigger(int(account_id), SyncMode.FastPull)


@route(PLUGIN_PREFIX + '/sync/push')
def Push(account_id=1, section=None, refresh=None):
    return Trigger(int(account_id), SyncMode.Push, section=section)


@route(PLUGIN_PREFIX + '/sync/pull')
def Pull(account_id=1, refresh=None):
    return Trigger(int(account_id), SyncMode.Pull)


def Trigger(account_id, mode, data=SyncData.All, media=SyncMedia.All, **kwargs):
    # TODO implement options to change `SyncData` option per `Account`

    try:
        Sync.queue(account_id, mode, data, media, **kwargs)
    except QueueError, ex:
        return redirect('/sync', account_id=account_id, title=ex.title, message=ex.message)

    return redirect('/sync', account_id=account_id)


@route(PLUGIN_PREFIX + '/sync/cancel')
def Cancel():
    if not Sync.cancel():
        return MessageContainer(
            L('cancel_failure:title'),
            L('cancel_failure:message'),
        )

    return MessageContainer(
        L('cancel_success:title'),
        L('cancel_success:message')
    )


class Active(object):
    @classmethod
    def create(cls, oc, callback, account=None):
        current = Sync.current

        if not current:
            # No task running
            return

        if account and current.account.id != account.id:
            # Only display status if `current` task matches provided `account`
            return

        # Create objects
        title = cls.build_title(current, account)

        oc.add(cls.build_status(current, title, callback))
        oc.add(cls.build_cancel(current, title))

    @staticmethod
    def build_title(current, account):
        if current.data == SyncData.All:
            # <mode>
            title = normalize(SyncMode.title(current.mode))
        else:
            # <mode> [<data>]
            title = '%s [%s]' % (
                normalize(SyncMode.title(current.mode)),
                normalize(SyncData.title(current.data))
            )

        # Task Progress
        percent = current.progress.percent

        if percent is not None:
            title += ' (%2d%%)' % percent

        # Account Name (only display outside of account-specific menus)
        if account is None:
            title += ' (%s)' % current.account.name

        return title

    #
    # Status
    #

    @classmethod
    def build_status(cls, current, title, callback=None):
        return DirectoryObject(
            key=callback,
            title=pad_title('%s - Status' % title),
            summary=cls.build_status_summary(current)
        )

    @staticmethod
    def build_status_summary(current):
        summary = 'Working'

        # Estimated time remaining
        remaining_seconds = current.progress.remaining_seconds

        if remaining_seconds is not None:
            summary += ', %.02f seconds remaining' % remaining_seconds

        return summary

    #
    # Cancel
    #

    @classmethod
    def build_cancel(cls, current, title):
        return DirectoryObject(
            key=Callback(Cancel, account_id=current.account.id),
            title=pad_title('%s - Cancel' % title)
        )


class Status(object):
    @classmethod
    def build(cls, account, mode, section=None):
        status = SyncResult.get_latest(account, mode, section).first()

        if status is None or status.latest is None:
            return 'Not run yet.'

        # Build status fragments
        fragments = []

        if status.latest.ended_at:
            # Build "Last run [...] ago" fragment
            fragments.append(cls.build_since(status))

            if status.latest.started_at:
                # Build "taking [...] seconds" fragment
                fragments.append(cls.build_elapsed(status))

        # Build result fragment (success, errors)
        fragments.append(cls.build_result(status))

        # Merge fragments
        if len(fragments):
            return ', '.join(fragments) + '.'

        return 'Not run yet.'

    @staticmethod
    def build_elapsed(status):
        elapsed = status.latest.ended_at - status.latest.started_at

        if elapsed.seconds < 1:
            return 'taking less than a second'

        return 'taking %s' % human(
            elapsed,
            precision=1,
            past_tense='%s'
        )

    @staticmethod
    def build_result(status):
        if status.latest.success:
            return 'was successful'

        message = 'failed'

        # Resolve errors
        errors = list(status.latest.get_errors())

        if len(errors) > 1:
            # Multiple errors
            message += ' (%d errors, %s)' % (len(errors), errors[0].summary)
        elif len(errors) == 1:
            # Single error
            message += ' (%s)' % errors[0].summary

        return message

    @staticmethod
    def build_since(status):
        since = datetime.utcnow() - status.latest.ended_at

        if since.seconds < 1:
            return 'Last run just a moment ago'

        return 'Last run %s' % human(since, precision=1)

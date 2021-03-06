from datetime import datetime, timedelta
from copy import copy

from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.db.models import Count, Prefetch
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.translation import ugettext as _, get_language

import arrow
from babel.dates import format_timedelta, format_datetime
from graphos.renderers import gchart
from graphos.sources.model import ModelDataSource

from counter.models import *
from counter.utils import parseSeumReason


@login_required
def get(request, id_counter):
    try:
        myCounter = Counter.objects.get(user__id=request.user.id)
    except Counter.DoesNotExist:
        return HttpResponseRedirect(reverse('login'))

    counter = Counter.objects.prefetch_related(
        # we get the related resets annotated with their number of likes
        Prefetch('resets', queryset=Reset.objects.select_related('who', 'counter').annotate(likes_count=Count('likes'))),
        'resets__likes'
    ).get(pk=id_counter)
    resets = list(counter.resets.order_by('-timestamp'))

    # Display
    if len(resets) == 0:
        counter.lastReset = Reset()
        counter.lastReset.delta = timedelta(0)
        counter.lastReset.noSeum = True
        seumFrequency = _('unknown')
    else:
        firstReset = copy(resets[-1])
        counter.lastReset = resets[0]
        counter.lastReset.noSeum = False
        if counter.lastReset.who is None or counter.lastReset.who == counter:
            counter.lastReset.selfSeum = True
        else:
            counter.lastReset.selfSeum = False

        counter.lastReset.formatted_delta = arrow.Arrow.fromdatetime(counter.lastReset.timestamp).humanize(locale=get_language())
        counter.seumCount = len(resets)
        seumFrequency = format_timedelta((datetime.now() - firstReset.timestamp.replace(tzinfo=None)) / counter.seumCount,
            locale=get_language(), threshold=1)

        counter.lastLikes = list(counter.lastReset.likes.all())
        counter.alreadyLiked = myCounter.id in [l.liker.id for l in counter.lastLikes]
        counter.likes_count = len(counter.lastLikes)
        if counter.likes_count > 0:
            counter.likersString = ", ".join(like.liker.trigramme for like in counter.lastLikes)

    for reset in resets:
        if reset.who is None or reset.who.id == reset.counter.id:
            reset.selfSeum = True
        else:
            reset.selfSeum = False
        reset.date = reset.timestamp

    # Timeline graph
    # Data pre-processing
    if not counter.lastReset.noSeum:
        resets_graph = resets
        for reset in resets_graph:
            reset.timestamp = {
                'v': reset.timestamp.timestamp(),
                'f': arrow.Arrow.fromdatetime(reset.timestamp).humanize(locale=get_language())
            }
            if reset.selfSeum:
                reset.Seum = {'v': 0, 'f': reset.reason}
            else:
                reset.Seum = {'v': 0, 'f': _('From %(who)s: %(reason)s') % {'who': reset.who.trigramme, 'reason': reset.reason}}

        # Drawing the graph
        data = ModelDataSource(resets, fields=['timestamp', 'Seum'])
        chart = gchart.LineChart(data, options={
            'lineWidth': 0,
            'pointSize': 10,
            'title': '',
            'vAxis': {'ticks': []},
            'hAxis': {'ticks': [{
                'v': firstReset.timestamp.timestamp(),
                'f': arrow.Arrow.fromdatetime(firstReset.timestamp).humanize(locale=get_language())
            }, {
                'v': datetime.now().timestamp(),
                'f': 'Présent'}
            ]},
            'legend': 'none',
            'height': 90
        })
    else:
        chart = None

    return render(request, 'counterTemplate.html', {
        'counter': counter,
        'chart': chart,
        'resets': resets,
        'seumFrequency': seumFrequency,
        'myCounter': myCounter,
    })


@login_required
def reset_counter(request):
    # Update Form counter
    if request.method == 'POST':
        # create a form instance and populate it with data from the request:
        data = dict(request.POST)

        who = Counter.objects.get(pk=int(data['who'][0]))
        reason = data['reason'][0]
        if 'counter' in data.keys():
            counter = Counter.objects.get(pk=int(data['counter'][0]))
        else:
            try:
                counter = Counter.objects.get(trigramme=data['trigramme'][0])
            except Counter.DoesNotExist:
                return HttpResponseRedirect(data['redirect'][0])

        # we check that the seumer is the autenticated user
        if who.user is None or who.user != request.user:
            return HttpResponseRedirect(data['redirect'][0])

        reason = data['reason'][0]
        perform_reset(who, counter, reason)

    return HttpResponseRedirect(data['redirect'][0])


def perform_reset(who, counter, reason):
    reset = Reset(counter=counter, who=who, reason=reason)

    reset.save()

    # Now we deal with the hashtags
    keywords = parseSeumReason(reason)
    Hashtag.objects.bulk_create([Hashtag(reset=reset, keyword=keyword) for keyword in keywords])

    # # We send the emails only to those who want
    # emails = [u['email'] for u in Counter.objects.filter(email_notifications=True).values('email')]
    # # Now send emails to everyone
    # if reset.who is None or reset.who == counter:
    #     selfSeum = True
    # else:
    #     selfSeum = False
    # text_of_email = render_to_string(
    #     'seumEmail.txt', {'reason': reason,
    #                       'name': counter.name,
    #                       'who': reset.who,
    #                       'selfSeum': selfSeum,
    #                       })
    # email_to_send = EmailMessage(
    #     '[SeumBook] ' + counter.trigramme + ' a le seum',
    #     text_of_email,
    #     'SeumMan <seum@merigoux.ovh>', emails, [],
    #     reply_to=emails)
    # email_to_send.send(fail_silently=True)

'''
@author:     Sid Probstein
@contact:    sidprobstein@gmail.com
'''

from sys import path
from os import environ
import logging as logger
from datetime import timedelta

import django
from django.utils import timezone

from swirl.utils import swirl_setdir
path.append(swirl_setdir()) # path to settings.py file
environ.setdefault('DJANGO_SETTINGS_MODULE', 'swirl_server.settings') 
django.setup()

from swirl.models import Search

module_name = 'expirer.py'

##################################################
##################################################

def expirer():

    '''
    This fires whenever a Celery Beat event arrives
    Remove searches that are past expiration date, if expiration is not 0
    '''
    
    searches = Search.objects.filter(retention__gt=0)
    for search in searches:
        if search.retention == 0:
            # don't delete - this should not happen because of the filter above
            logger.warning(f"{module_name}: filter error, reviewed a search with retention = {search.retention}")
            continue
        else:
            expired = False
            if search.retention == 1:
                if search.date_updated + timedelta(hours=1) < timezone.now():
                    expired = True
            elif search.retention == 2:
                if search.date_updated + timedelta(days=1) < timezone.now():
                    expired = True
            elif search.retention == 3:
                if search.date_updated + timedelta(month=1) < timezone.now():
                    expired = True
            else:
                logger.error(f"{module_name}: unexpected retention setting: {search.retention}")
            if expired:
                # to do: fix this to show local time, someday P4
                logger.info(f"{module_name}: expiring search: {search.id} updated {search.date_updated} with retention {search.retention}")
                search.delete()
            # end if
        # end if
    # end for

    return True
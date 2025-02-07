#  This file is part of wger Workout Manager <https://github.com/wger-project>.
#  Copyright (C) 2013 - 2021 wger Team
#
#  wger Workout Manager is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  wger Workout Manager is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Standard Library
import pathlib
import uuid

# Django
from django.core import mail
from django.db import models
from django.utils.translation import gettext_lazy as _

# wger
from wger.core.models import Language
from wger.exercises.models import ExerciseBase
from wger.utils.cache import delete_template_fragment_cache
from wger.utils.managers import SubmissionManager
from wger.utils.models import (
    AbstractLicenseModel,
    AbstractSubmissionModel,
)


def exercise_image_upload_dir(instance, filename):
    """
    Returns the upload target for exercise images
    """
    ext = pathlib.Path(filename).suffix
    return "exercise-images/{0}/{1}{2}".format(instance.exercise_base.id, instance.uuid, ext)


class ExerciseImage(AbstractSubmissionModel, AbstractLicenseModel, models.Model):
    """
    Model for an exercise image
    """

    objects = SubmissionManager()
    """Custom manager"""

    LINE_ART = '1'
    THREE_D = '2'
    LOW_POLY = '3'
    PHOTO = '4'
    OTHER = '5'
    STYLE = (
        (LINE_ART, _('Line')),
        (THREE_D, _('3D')),
        (LOW_POLY, _('Low-poly')),
        (PHOTO, _('Photo')),
        (OTHER, _('Other')),
    )

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        verbose_name='UUID',
    )
    """Globally unique ID, to identify the image across installations"""

    exercise_base = models.ForeignKey(
        ExerciseBase,
        verbose_name=_('Exercise'),
        on_delete=models.CASCADE,
    )
    """The exercise the image belongs to"""

    image = models.ImageField(
        verbose_name=_('Image'),
        help_text=_('Only PNG and JPEG formats are supported'),
        upload_to=exercise_image_upload_dir,
    )
    """Uploaded image"""

    is_main = models.BooleanField(
        verbose_name=_('Main picture'),
        default=False,
        help_text=_(
            "Tick the box if you want to set this image as the "
            "main one for the exercise (will be shown e.g. in "
            "the search). The first image is automatically "
            "marked by the system."
        )
    )
    """A flag indicating whether the image is the exercise's main image"""

    style = models.CharField(
        help_text=_('The art style of your image'),
        max_length=1,
        choices=STYLE,
        default=PHOTO,
    )
    """The art style of the image"""

    class Meta:
        """
        Set default ordering
        """
        ordering = ['-is_main', 'id']
        base_manager_name = 'objects'

    def save(self, *args, **kwargs):
        """
        Only one image can be marked as main picture at a time
        """
        if self.is_main:
            ExerciseImage.objects.filter(exercise_base=self.exercise_base).update(is_main=False)
            self.is_main = True
        else:
            if ExerciseImage.objects.accepted()\
                .filter(exercise_base=self.exercise_base).count() == 0 \
               or not ExerciseImage.objects.accepted() \
                    .filter(exercise_base=self.exercise_base, is_main=True)\
                    .count():

                self.is_main = True

        #
        # Reset all cached infos
        #
        for language in Language.objects.all():
            delete_template_fragment_cache('muscle-overview', language.id)
            delete_template_fragment_cache('exercise-overview', language.id)
            delete_template_fragment_cache('exercise-overview-mobile', language.id)
            delete_template_fragment_cache('equipment-overview', language.id)

        # And go on
        super(ExerciseImage, self).save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """
        Reset all cached infos
        """
        super(ExerciseImage, self).delete(*args, **kwargs)

        for language in Language.objects.all():
            delete_template_fragment_cache('muscle-overview', language.id)
            delete_template_fragment_cache('exercise-overview', language.id)
            delete_template_fragment_cache('exercise-overview-mobile', language.id)
            delete_template_fragment_cache('equipment-overview', language.id)

        # Make sure there is always a main image
        if not ExerciseImage.objects.accepted().filter(
            exercise_base=self.exercise_base, is_main=True
        ).count() and ExerciseImage.objects.accepted().filter(exercise_base=self.exercise_base
                                                              ).filter(is_main=False).count():

            image = ExerciseImage.objects.accepted() \
                .filter(exercise_base=self.exercise_base, is_main=False)[0]
            image.is_main = True
            image.save()

    def get_owner_object(self):
        """
        Image has no owner information
        """
        return False

    def set_author(self, request):
        """
        Set author and status
        This is only used when creating images (via web or API)
        """
        if request.user.has_perm('exercises.add_exerciseimage'):
            self.status = self.STATUS_ACCEPTED
            if not self.license_author:
                self.license_author = request.get_host().split(':')[0]

        else:
            if not self.license_author:
                self.license_author = request.user.username

            subject = _('New user submitted image')
            message = _('The user {0} submitted a new image "{1}" for exercise {2}.'
                        ).format(request.user.username, self.name, self.exercise)
            mail.mail_admins(
                str(subject),
                str(message),
                fail_silently=True,
            )

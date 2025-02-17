"""Mix-in classes for project views."""
import structlog
from datetime import timedelta
from functools import lru_cache

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from readthedocs.projects.exceptions import ProjectSpamError
from readthedocs.projects.models import Project

log = structlog.get_logger(__name__)


class ProjectOnboardMixin:

    """Add project onboard context data to project object views."""

    def get_context_data(self, **kwargs):
        """Add onboard context data."""
        context = super().get_context_data(**kwargs)
        # If more than 1 project, don't show onboarding at all. This could
        # change in the future, to onboard each user maybe?
        if Project.objects.for_admin_user(self.request.user).count() > 1:
            return context

        onboard = {}
        project = self.get_object()

        # Show for the first few builds, return last build state
        if project.builds.count() <= 5:
            onboard['build'] = project.get_latest_build(finished=False)
            if 'github' in project.repo:
                onboard['provider'] = 'github'
            elif 'bitbucket' in project.repo:
                onboard['provider'] = 'bitbucket'
            elif 'gitlab' in project.repo:
                onboard['provider'] = 'gitlab'
            context['onboard'] = onboard

        return context


# Mixins
class ProjectAdminMixin:

    """
    Mixin class that provides project sublevel objects.

    This mixin uses several class level variables

    project_url_field
        The URL kwarg name for the project slug
    """

    project_url_field = 'project_slug'

    def get_queryset(self):
        self.project = self.get_project()
        return self.model.objects.filter(project=self.project)

    @lru_cache(maxsize=1)
    def get_project(self):
        """Return project determined by url kwarg."""
        if self.project_url_field not in self.kwargs:
            return None
        return get_object_or_404(
            Project.objects.for_admin_user(user=self.request.user),
            slug=self.kwargs[self.project_url_field],
        )

    def get_context_data(self, **kwargs):
        """Add project to context data."""
        context = super().get_context_data(**kwargs)
        context['project'] = self.get_project()
        return context

    def get_form(self, data=None, files=None, **kwargs):
        """Pass in project to form class instance."""
        kwargs['project'] = self.get_project()
        return self.form_class(data, files, **kwargs)


class ProjectSpamMixin:

    """Protects POST views from spammers."""

    def post(self, request, *args, **kwargs):
        log.bind(user_username=request.user.username)
        if request.user.profile.banned:
            log.info('Rejecting project POST from shadowbanned user.')
            return HttpResponseRedirect(self.get_failure_url())
        try:
            return super().post(request, *args, **kwargs)
        except ProjectSpamError:
            date_maturity = timezone.now() - timedelta(
                days=settings.USER_MATURITY_DAYS
            )
            if request.user.date_joined > date_maturity:
                request.user.profile.banned = True
                request.user.profile.save()
                log.info('Spam detected from new user, shadowbanned user.')
            else:
                log.info('Spam detected from user.')
            return HttpResponseRedirect(self.get_failure_url())

    def get_failure_url(self):
        return reverse('homepage')

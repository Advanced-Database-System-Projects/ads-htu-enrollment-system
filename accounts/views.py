from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.models import User
from accounts.permissions import (
    get_dashboard_url,
    get_instructor_for_user,
    get_student_for_user,
    role_required,
)


class RoleAwareLoginView(LoginView):
    """Login view that routes authenticated users to their role dashboard.

    A stale authenticated session for an inactive account is logged out
    before the login form is rendered, preventing a redirect loop between
    the login page and a dashboard the account may not access.
    """

    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_active:
            logout(request)
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        redirect_to = self.get_redirect_url()
        if redirect_to and redirect_to != self.request.path:
            return redirect_to
        return reverse(get_dashboard_url(self.request.user))


@login_required
def dashboard(request):
    """Role-aware dashboard dispatcher."""
    if not request.user.is_active:
        logout(request)
        return redirect("login")
    return redirect(get_dashboard_url(request.user))


@role_required(User.Role.STUDENT)
def student_dashboard(request):
    from django.db.models import Q
    from django.utils import timezone
    from academics.models import AcademicTerm
    from enrollment.models import Enrollment, EnrollmentDetail
    from finance.models import Assessment

    student = get_student_for_user(request.user)

    enrollment = None
    details = []
    assessment = None

    if student:
        today = timezone.localdate()
        current_term = (
            AcademicTerm.objects
            .filter(start_date__lte=today, end_date__gte=today)
            .order_by('-academic_year', 'semester_number')
            .first()
        )

        if current_term:
            enrollment = (
                Enrollment.objects
                .filter(student=student, term=current_term)
                .exclude(status=Enrollment.Status.CANCELLED)
                .select_related('term', 'assessment')
                .order_by('-enrollment_date', '-pk')
                .first()
            )

        if enrollment is None:
            enrollment = (
                Enrollment.objects
                .filter(student=student)
                .exclude(status=Enrollment.Status.CANCELLED)
                .select_related('term', 'assessment')
                .order_by('-term__academic_year', '-term__semester_number', '-enrollment_date')
                .first()
            )

        if enrollment is not None:
            details = list(
                EnrollmentDetail.objects
                .filter(enrollment=enrollment, status=EnrollmentDetail.Status.ENROLLED)
                .select_related('section__course', 'section__instructor__user', 'section__room')
                .order_by('section__course__course_code', 'section__section_code')
            )
            try:
                assessment = enrollment.assessment
            except Assessment.DoesNotExist:
                assessment = None

    return render(request, "accounts/dashboards/student.html", {
        "student": student,
        "enrollment": enrollment,
        "details": details,
        "assessment": assessment,
    })


@role_required(User.Role.INSTRUCTOR)
def instructor_dashboard(request):
    from django.db.models import Count, Q
    from django.utils import timezone
    from academics.models import AcademicTerm
    from enrollment.models import Enrollment, EnrollmentDetail

    instructor = get_instructor_for_user(request.user)

    today = timezone.localdate()
    current_term = (
        AcademicTerm.objects
        .filter(start_date__lte=today, end_date__gte=today)
        .order_by('-academic_year', 'semester_number')
        .first()
    ) or AcademicTerm.objects.order_by('-academic_year', 'semester_number').first()

    sections = []
    total_confirmed = 0
    total_pending = 0

    if instructor and current_term:
        from scheduling.models import Section
        sections = list(
            Section.objects
            .filter(instructor=instructor, term=current_term)
            .select_related('course', 'term', 'room')
            .annotate(
                confirmed_count=Count(
                    'enrollment_details',
                    filter=(
                        Q(enrollment_details__status=EnrollmentDetail.Status.ENROLLED) &
                        Q(enrollment_details__enrollment__status=Enrollment.Status.CONFIRMED)
                    ),
                    distinct=True,
                ),
                pending_count=Count(
                    'enrollment_details',
                    filter=(
                        Q(enrollment_details__status=EnrollmentDetail.Status.ENROLLED) &
                        Q(enrollment_details__enrollment__status=Enrollment.Status.DRAFT)
                    ),
                    distinct=True,
                ),
            )
            .order_by('course__course_code', 'section_code')
        )
        total_confirmed = sum(s.confirmed_count for s in sections)
        total_pending = sum(s.pending_count for s in sections)

    return render(request, "accounts/dashboards/instructor.html", {
        "instructor": instructor,
        "current_term": current_term,
        "sections": sections,
        "total_confirmed": total_confirmed,
        "total_pending": total_pending,
    })


@role_required(User.Role.CASHIER)
def cashier_dashboard(request):
    return render(request, "accounts/dashboards/cashier.html")


@role_required(User.Role.REGISTRAR)
def registrar_dashboard(request):
    return render(request, "accounts/dashboards/registrar.html")


@role_required(User.Role.ADMINISTRATOR)
def administrator_dashboard(request):
    return render(request, "accounts/dashboards/administrator.html")

"""
App-independent tests for Approval models - no app logic
"""
from django.core import exceptions
from django.test import SimpleTestCase, TestCase
from signoffs.core.approvals import BaseApproval
import signoffs.core.signing_order as so
from signoffs.registry import approvals, register

from .models import Stamp, OtherStamp, ApprovalSignoff, LeaveApproval
from . import fixtures


@register(id='signoffs.tests.my_approval')
class MyApproval(BaseApproval):
    stampModel = Stamp
    label = 'Test Approval'

    first_signoff = ApprovalSignoff.register(id='test.approval.first')
    second_signoff = ApprovalSignoff.register(id='test.approval.second')
    final_signoff = ApprovalSignoff.register(id='test.approval.final')

    signing_order = so.SigningOrder(
        first_signoff,
        so.AtLeastN(second_signoff, n=2),
        final_signoff
    )


class SimpleApprovalTypeTests(SimpleTestCase):
    def test_approval_type_relations(self):
        approval_type = approvals.get('signoffs.tests.my_approval')
        approval = approval_type()
        self.assertEqual(approval.stamp_model, Stamp)
        stamp = approval.stamp
        self.assertEqual(stamp.approval_type, approval_type)
        self.assertEqual(stamp.approval, approval)

    def test_with_no_stamp(self):
        with self.assertRaises(exceptions.ImproperlyConfigured):
            MyApproval.register(id='test.invalid.no_stamp', stampModel=None)


class ApprovalTypeIntheritanceTests(SimpleTestCase):
    def test_class_var_overrides(self):
        a = MyApproval.register('signoff.test.my_approval.test1')
        self.assertEqual(a.label, MyApproval.label)
        self.assertEqual(a().stamp_model, Stamp)

    def test_field_override(self):
        a = MyApproval.register('signoff.test.my_approval.test2',
                                label='Something', revoke_perm='auth.some_perm', stampModel=OtherStamp)
        self.assertEqual(a.label, 'Something')
        self.assertEqual(a.revoke_perm, 'auth.some_perm')
        self.assertEqual(a().stamp_model, OtherStamp)


class ApprovalTypeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restricted_user = fixtures.get_user(username='restricted')
        cls.approving_user = fixtures.get_user(username='approving', perms=('some_perm',))
        cls.unrestricted_user = fixtures.get_user(username='permitted', perms=('some_perm', 'revoke_perm'))

    def test_init(self):
        stamp = Stamp(approval_id=MyApproval.id)
        a1 = MyApproval(stamp=stamp)  # with explicit stamp
        self.assertEqual(a1.stamp, stamp)
        self.assertEqual(stamp.get_approval(), a1)

        a2 = MyApproval()  # default approval
        self.assertTrue(isinstance(a2.stamp, Stamp))
        self.assertEqual(a2.stamp.approval_id, MyApproval.id)
        self.assertFalse(a2.stamp.is_approved())

    def test_invalid_init(self):
        a1 = MyApproval.register('signoff.test.my_approval.test3',
                                 perm='some_perm', stampModel=OtherStamp)
        stamp = Stamp(approval_id=MyApproval.id)
        with self.assertRaises(exceptions.ImproperlyConfigured):
            a1(stamp=stamp)                   # stamp model does not match approval
        a = a1()
        self.assertFalse(a.can_revoke(user=self.restricted_user))  # approval requires permission
        with self.assertRaises(exceptions.PermissionDenied):
            a.revoke(user=self.restricted_user)

    def test_create(self):
        a = MyApproval.create()
        self.assertFalse(a.is_approved())


class SigningOrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restricted_user = fixtures.get_user(username='restricted')
        cls.approving_user = fixtures.get_user(username='approving', perms=('some_perm',))
        cls.unrestricted_user = fixtures.get_user(username='permitted', perms=('some_perm', 'revoke_perm'))
        cls.approval = MyApproval().save()

    def test_next_signoffs(self):
        u = self.unrestricted_user
        next = self.approval.next_signoffs(for_user=u)
        self.assertEqual(len(next), 1)
        self.assertEqual(next[0].id, MyApproval.first_signoff.id)
        self.assertEqual(next[0].signet.stamp, self.approval.stamp)
        self.assertTrue(next[0].can_sign(user=u))
        next[0].sign(user=u)
        self.assertEqual(self.approval.signatories.count(), 1)
        next = self.approval.next_signoffs(for_user=u)
        self.assertEqual(len(next), 1)
        self.assertEqual(next[0].id, MyApproval.second_signoff.id)

    def test_can_sign(self):
        u = self.unrestricted_user
        self.assertTrue(self.approval.can_sign(user=u))

    def test_is_complete(self):
        self.assertFalse(self.approval.is_complete())
        u = self.unrestricted_user
        self.approval.next_signoffs(for_user=u)[0].sign(user=u)
        self.approval.next_signoffs(for_user=u)[0].sign(user=u)
        u2 = self.approving_user
        self.approval.next_signoffs(for_user=u2)[0].sign(user=u)
        self.assertFalse(self.approval.is_complete())

        next = self.approval.next_signoffs(for_user=u)
        self.assertEqual(len(next), 2)
        final = [s for s in next if s.id == MyApproval.final_signoff.id][0]
        final.sign(user=u)
        self.assertTrue(self.approval.is_complete())


class ApprovalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = fixtures.get_user()
        cls.approval = MyApproval().save()

    def test_next_signoffs(self):
        u = self.user
        # One first_signoff
        next = self.approval.next_signoffs(for_user=u)
        self.assertEqual(next[0].id, MyApproval.first_signoff.id)
        next[0].sign(user=u)
        # Two second_signoffs
        next = self.approval.next_signoffs(for_user=u)
        self.assertEqual(next[0].id, MyApproval.second_signoff.id)
        next[0].sign(user=u)
        next = self.approval.next_signoffs(for_user=u)
        self.assertEqual(next[0].id, MyApproval.second_signoff.id)
        next[0].sign(user=u)
        next = self.approval.next_signoffs(for_user=u)
        self.assertSetEqual({s.id for s in next}, {MyApproval.second_signoff.id, MyApproval.final_signoff.id})
        self.assertFalse(self.approval.is_complete() or self.approval.is_approved())
        final_signoff = [s for s in next if s.id == MyApproval.final_signoff.id][0]
        final_signoff.sign(user=u)
        self.assertTrue(self.approval.is_complete())
        self.assertFalse(self.approval.is_approved())
        self.approval.approve_if_ready()
        self.assertTrue(self.approval.is_approved())


class ApprovalQuerysetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.myapprovals= [
            MyApproval.create(),
            MyApproval.create(approved=True),
            MyApproval.create(),
        ]
        cls.leaveapprovals= [
            LeaveApproval.create(approved=True),
            LeaveApproval.create(),
        ]

    def test_stamp_queryset(self):
        myapproval_qs = MyApproval.get_stamp_queryset().approvals()
        self.assertListEqual(myapproval_qs, self.myapprovals)
        leaveapproval_qs = LeaveApproval.get_stamp_queryset().approvals()
        self.assertListEqual(leaveapproval_qs, self.leaveapprovals)

    def test_stamp_queryset_filter(self):
        approved_qs = MyApproval.get_stamp_queryset().filter(approved=True).approvals()
        self.assertListEqual(approved_qs,
                             [a for a in self.myapprovals if a.is_approved()])


class StampModelTests(TestCase):
    def test_valid_approval_type(self):
        a = approvals.get('signoffs.tests.my_approval')
        p = Stamp(approval_id='signoffs.tests.my_approval')
        self.assertEqual(p.approval_type, a)

    def test_invalid_approval_type(self):
        p = Stamp(approval_id='not.a.valid.type')
        with self.assertRaises(exceptions.ImproperlyConfigured):
            self.assertFalse(p.approval_type)

    def test_signatories(self):
        p = Stamp(approval_id='signoffs.tests.my_approval')
        p.save()
        u = fixtures.get_user(username='daffyduck')
        p.signatories.create(user=u, stamp=p, signoff_id='test.approval.first')
        self.assertTrue(p.is_user_signatory(u))

    def approve(self):
        p = Stamp(approval_id='signoffs.tests.my_approval')
        p.approve()
        p.save()
        self.assertTrue(p.is_approved())


class StampQuerysetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        u = fixtures.get_user()
        set1 = (
            MyApproval.create(),
            MyApproval.create(),
        )
        set2 = (
            LeaveApproval.create(),
            LeaveApproval.create(),
            LeaveApproval.create(),
        )
        cls.all_approvals = set1 + set2
        cls.approval_set1, cls.approval_set2 = set1, set2
        cls.user = u

    def test_qs_basics(self):
        approvals = Stamp.objects.filter(approval_id=MyApproval.id)
        self.assertQuerysetEqual(approvals.order_by('pk'), [a.stamp for a in self.approval_set1])

    def test_qs_approvals(self):
        approvals = MyApproval.get_stamp_queryset().approvals()
        self.assertQuerysetEqual(approvals, self.approval_set1)

    def test_qs_approvals_filter(self):
        base_qs = Stamp.objects.order_by('pk')
        self.assertQuerysetEqual(base_qs.approvals(approval_id=MyApproval.id), self.approval_set1)
        self.assertQuerysetEqual(base_qs.approvals(approval_id=LeaveApproval.id), self.approval_set2)

    def test_qs_approvals_performance(self):
        base_qs = Stamp.objects.all().order_by('pk')
        with self.assertNumQueries(1):
            approvals1 = base_qs.approvals(approval_id=MyApproval.id)
            self.assertEqual(len(approvals1), len(self.approval_set1))
            approvals2 = base_qs.approvals(approval_id=LeaveApproval.id)
            self.assertEqual(len(approvals2), len(self.approval_set2))
            self.assertEqual(len(base_qs.approvals()), len(self.all_approvals))

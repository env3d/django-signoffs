"""
App-independent tests for Signoff models - no app logic
"""
from django.core import exceptions
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from signoffs.registry import signoffs

from .models import Signet, OtherSignet, BasicSignoff
from . import fixtures


signoff1 = BasicSignoff.register(id='test.signoff1')
signoff2 = BasicSignoff.register(id='test.signoff2', signetModel=OtherSignet,
                                 label='Something', perm='auth.some_perm', revoke_perm='auth.revoke_perm')
signoff3 = BasicSignoff.register(id='test.signoff3')


class SimpleSignoffTypeTests(SimpleTestCase):
    def test_signoff_type_relations(self):
        signoff_type = signoffs.get('test.signoff1')
        signoff = signoff_type()
        self.assertEqual(signoff.signet_model, Signet)
        signet = signoff.signet
        self.assertEqual(signet.signoff_type, signoff_type)
        self.assertEqual(signet.signoff, signoff)

    def test_with_no_signet(self):
        with self.assertRaises(exceptions.ImproperlyConfigured):
            BasicSignoff.register(id='test.invalid.no_signet', signetModel=None)


class SignoffTypeIntheritanceTests(SimpleTestCase):
    def test_class_var_overrides(self):
        s = signoffs.get('test.signoff1')
        self.assertEqual(s.label, BasicSignoff.label)
        self.assertEqual(s().signet_model, Signet)

    def test_field_override(self):
        s = signoffs.get('test.signoff2')
        self.assertEqual(s.label, 'Something')
        self.assertEqual(s.perm, 'auth.some_perm')
        self.assertEqual(s().signet_model, OtherSignet)


class SignoffTypeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restricted_user = fixtures.get_user(username='restricted')
        cls.signing_user = fixtures.get_user(username='signing', perms=('some_perm',))
        cls.unrestricted_user = fixtures.get_user(username='permitted', perms=('some_perm', 'revoke_perm'))

    def test_init(self):
        signet = Signet(signoff_id=signoff1.id)
        so1 = signoff1(signet=signet)  # with explicit signet
        self.assertEqual(so1.signet, signet)

        so2 = signoff1()  # default, unsigned signoff
        self.assertTrue(isinstance(so2.signet, Signet))
        self.assertEqual(so2.signet.signoff_id, signoff1.id)
        self.assertFalse(so2.signet.has_user())

        so3 = signoff1(user=self.signing_user, sigil='custom sigil')  # with signet construction args
        self.assertEqual(so3.signet.user, self.signing_user)
        self.assertEqual(so3.signet.sigil, 'custom sigil')

    def test_invalid_init(self):
        signet = Signet(signoff_id=signoff1.id)
        with self.assertRaises(exceptions.ImproperlyConfigured):
            signoff1(signet=signet, user=self.signing_user)  # supply either signet OR signet create kwargs
        with self.assertRaises(exceptions.ImproperlyConfigured):
            signoff2(signet=signet, user=self.signing_user)  # signet model does not match signoff
        so = signoff2(user=self.restricted_user)    # signoff requires permission
        self.assertFalse(so.can_save())
        with self.assertRaises(exceptions.PermissionDenied):
            so.save()

    def test_can_sign(self):
        unrestricted_so = signoff1()
        restricted_so = signoff2()
        self.assertTrue(unrestricted_so.can_sign(self.restricted_user))
        self.assertFalse(restricted_so.can_sign(self.restricted_user))
        self.assertTrue(restricted_so.can_sign(self.signing_user))

    def test_can_revoke(self):
        unrestricted_so = signoff1(user=self.unrestricted_user).save()
        restricted_so = signoff2(user=self.unrestricted_user).save()
        self.assertTrue(unrestricted_so.can_revoke(self.restricted_user))
        self.assertFalse(restricted_so.can_revoke(self.restricted_user))
        self.assertFalse(restricted_so.can_revoke(self.signing_user))
        self.assertTrue(restricted_so.can_revoke(self.unrestricted_user))

    def test_irrevokable(self):
        signoff = BasicSignoff.register(id='test.irrevokable', revoke_perm=False)
        self.assertFalse(signoff.is_permitted_revoker(self.unrestricted_user))
        irrevokable_so = signoff(user=self.signing_user).save()
        self.assertFalse(irrevokable_so.can_revoke(self.unrestricted_user))

    def test_create(self):
        so = signoff2.create(user=self.signing_user)
        self.assertTrue(so.is_signed)

    def test_default_sigil(self):
        so = signoff2.create(user=self.signing_user)
        self.assertEqual(so.signet.sigil, self.signing_user.get_full_name())


class SignoffQuerysetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        u = fixtures.get_user(perms=('some_perm',))
        cls.user = u
        u2 = fixtures.get_user(perms=('some_perm',))

        cls.signoff1s= [
            signoff1.create(user=u,),
            signoff1.create(user=u2, ),
            signoff1.create(user=u, ),
        ]
        cls.signoff2s= [
            signoff2.create(user=u2,),
            signoff2.create(user=u, ),
        ]
        cls.signoff3s= [
            signoff3.create(user=u,),
        ]

    def test_signet_queryset(self):
        so1_qs = signoff1.get_signet_queryset().signoffs()
        self.assertListEqual(so1_qs, self.signoff1s)
        so2_qs = signoff2.get_signet_queryset().signoffs()
        self.assertListEqual(so2_qs, self.signoff2s)
        so3_qs = signoff3.get_signet_queryset().signoffs()
        self.assertListEqual(so3_qs, self.signoff3s)

    def test_signet_queryset_filter(self):
        so_qs = signoff1.get_signet_queryset().filter(user=self.user).signoffs()
        self.assertListEqual(so_qs,
                             [so for so in self.signoff1s if so.signet.user==self.user])

class SignetModelTests(SimpleTestCase):
    def test_default_signature(self):
        u = get_user_model()(username='daffyduck')
        o = Signet(signoff_id='test.signoff1', user=u)
        self.assertEqual(o.get_signet_defaults()['sigil'], 'daffyduck')
        u = get_user_model()(username='daffyduck', first_name='Daffy', last_name='Duck')
        o = Signet(signoff_id='test.signoff1', user=u)
        self.assertEqual(o.get_signet_defaults()['sigil'], 'Daffy Duck')

    def test_valid_signoff_type(self):
        s = signoffs.get('test.signoff1')
        o = Signet(signoff_id='test.signoff1')
        self.assertEqual(o.signoff_type, s)

    def test_invalid_signoff_type(self):
        o = Signet(signoff_id='not.a.valid.type')
        with self.assertRaises(exceptions.ImproperlyConfigured):
            self.assertFalse(o.signoff_type)


class SignetQuerysetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = fixtures.get_user(first_name='Daffy', last_name='Duck', username='quacker')
        signoff1_set = (
            signoff1.create(user=user),
            signoff1.create(user=user),
        )
        signoff3_set = (
            signoff3.create(user=user),
            signoff3.create(user=user),
            signoff3.create(user=user),
        )
        cls.signoff1_set = signoff1_set
        cls.signoff3_set = signoff3_set
        cls.all_signoffs = signoff1_set + signoff3_set
        cls.user = user

    def test_qs_basics(self):
        signoff_set = Signet.objects.filter(signoff_id='test.signoff1')
        self.assertQuerysetEqual(signoff_set.order_by('pk'), [so.signet for so in self.signoff1_set])

    def test_qs_signoffs(self):
        signoff_set = Signet.objects.order_by('pk').filter(signoff_id='test.signoff1').signoffs()
        self.assertQuerysetEqual(signoff_set, self.signoff1_set)

    def test_qs_signoffs_filter(self):
        base_qs = Signet.objects.order_by('pk')
        self.assertQuerysetEqual(base_qs.signoffs(signoff_id='test.signoff1'), self.signoff1_set)
        self.assertQuerysetEqual(base_qs.signoffs(signoff_id='test.signoff2'), [])
        self.assertQuerysetEqual(base_qs.signoffs(signoff_id='test.signoff3'), self.signoff3_set)

    def test_qs_signoffs_performance(self):
        base_qs = Signet.objects.all().order_by('pk')
        with self.assertNumQueries(1):
            signoffs1 = base_qs.signoffs(signoff_id='test.signoff1')
            self.assertEqual(len(signoffs1), len(self.signoff1_set))
            signoffs2 = base_qs.signoffs(signoff_id='test.signoff2')
            self.assertEqual(len(signoffs2), 0)
            signoffs3 = base_qs.signoffs(signoff_id='test.signoff3')
            self.assertEqual(len(signoffs3), len(self.signoff3_set))
            self.assertEqual(len(base_qs.signoffs()), len(self.all_signoffs))

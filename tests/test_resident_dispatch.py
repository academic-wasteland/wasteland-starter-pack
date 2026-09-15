import sys
import types
import unittest
from unittest.mock import Mock, patch

from wasteland.bridge import Bridge


class ResidentDispatchTests(unittest.TestCase):
    def test_named_residents_are_claimed_before_generic_research_dispatch(self):
        exchange = types.ModuleType('pangenome_town.exchange')
        exchange.Envelope = types.SimpleNamespace(from_dict=lambda message: message)
        bridge = object.__new__(Bridge)
        bridge.town = types.SimpleNamespace(name='ubar')
        for resident in ('q', 'bloodninja', 'contact', None, 'not_a_resident'):
            bridge.log = Mock()
            message = {'id': 'request', 'from': 'visitor', 'kind': 'question',
                       'body': {'operation': 'message', 'resident': resident}}
            with patch.dict(sys.modules, {'pangenome_town.exchange': exchange}):
                bridge.received(message)
            bridge.log.set_status.assert_called_with('request', 'dispatched')
            self.assertTrue(any(call.args[1] == 'dispatched' and call.args[3]['resident'] == resident
                                for call in bridge.log.event.call_args_list))

    def test_general_contact_answers_without_delivering_to_research_agents(self):
        contacts = types.ModuleType('pangenome_town.contacts')
        contacts.directory = Mock(return_value={'ok': True, 'resident': 'contact', 'text': 'Welcome'})
        bridge = object.__new__(Bridge)
        bridge.town = types.SimpleNamespace(name='ubar')
        bridge.deliver = Mock(side_effect=AssertionError('general contact must not launch an agent'))
        with patch.dict(sys.modules, {'pangenome_town.contacts': contacts}):
            for resident in (None, 'contact', 'guide'):
                result = bridge.handle({'body': {'operation': 'message', 'resident': resident}}, {})
                self.assertEqual(result['text'], 'Welcome')
        contacts.directory.assert_called_with(bridge.town, public=True)

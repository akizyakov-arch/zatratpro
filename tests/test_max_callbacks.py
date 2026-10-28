"""Native callback UI uses Telegram labels and platform-authenticated actors."""
import copy
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx

from db_fixture import DatabaseFixture
from test_max_adapter import message
from app.max_bot.client import MaxAPIError, MaxClient
from app.max_bot.handler import MaxHandler, event_message
from app.max_bot.menu import CALLBACK_PREFIX, MenuButton, MenuText
from app.max_bot.runner import process_batch
from app.max_bot.telegram_ui import keyboard
from app.services.account_links import AccountLinkService
from app.ui import company as ui


def labels(markup):
    return [[button.text for button in row] for row in markup.inline_keyboard]


class CallbackTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_visible_name_and_hidden_action_are_sent_separately(self):
        requests = []
        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={})
        async with MaxClient('test', transport=httpx.MockTransport(transport)) as client:
            await client.send(55, MenuText('Активные проекты:', [[MenuButton('Ривер Дон', '/project 17')]]))
            await client.answer('callback-id')
        button = json.loads(requests[0].content)['attachments'][0]['payload']['buttons'][0][0]
        self.assertEqual(button, {'type': 'callback', 'text': 'Ривер Дон', 'payload': CALLBACK_PREFIX + '/project 17'})
        self.assertEqual(requests[1].url.path, '/answers')
        self.assertEqual(requests[1].url.params['callback_id'], 'callback-id')
        self.assertEqual(json.loads(requests[1].content), {})

    async def test_panel_link_is_native_link_not_callback_or_message(self):
        from app.max_bot.menu import LinkButton
        sent = []
        async with MaxClient('test', transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200, json={}))) as client:
            await client.send(55, MenuText('Панель', [[LinkButton('Открыть панель', 'https://panel.example')]]))
        button = json.loads(sent[0].content)['attachments'][0]['payload']['buttons'][0][0]
        self.assertEqual(button, {'type': 'link', 'text': 'Открыть панель', 'url': 'https://panel.example'})

    async def test_same_names_have_distinct_actions_and_long_names_fit_max(self):
        rows = keyboard(ui.build_projects_keyboard([SimpleNamespace(id=11, name='Одинаково'), SimpleNamespace(id=22, name='Одинаково')], False))
        self.assertEqual(rows[0][0], rows[1][0])
        self.assertNotEqual(rows[0][0].command, rows[1][0].command)
        sent = []
        async with MaxClient('test', transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200, json={}))) as client:
            await client.send(55, MenuText('Проекты', [[MenuButton('Я'*200, '/project 11')]]))
        self.assertEqual(len(json.loads(sent[0].content)['attachments'][0]['payload']['buttons'][0][0]['text']), 128)

    async def test_callback_actor_comes_from_user_not_original_message_sender(self):
        event = message(55, MenuButton('Название проекта', '/project 17'))
        event['message']['sender'] = {'user_id': 999999, 'is_bot': True}
        self.assertEqual(event_message(event), (55, '/project 17'))
        event['message']['recipient']['user_id'] = None
        self.assertEqual(event_message(event), (55, '/project 17'))
        for mutate in (
            lambda e: e['message']['recipient'].update(chat_type='chat'),
            lambda e: e['message']['recipient'].update(user_id=56),
            lambda e: e['callback']['user'].update(user_id=True),
            lambda e: e['callback']['user'].update(is_bot=True),
            lambda e: e['callback'].update(payload='/project 17'),
            lambda e: e['callback'].update(callback_id=''),
            lambda e: e.update(message=None),
        ):
            bad = copy.deepcopy(event)
            mutate(bad)
            self.assertIsNone(event_message(bad))

    async def test_callback_is_answered_and_expired_answer_does_not_block_reply(self):
        event = message(55, MenuButton('Назад', '/start'))
        for error in (None, MaxAPIError('expired', status=404)):
            client = SimpleNamespace(answer=AsyncMock(side_effect=error), send=AsyncMock())
            handler = SimpleNamespace(handle=AsyncMock(return_value=(55, 'Меню')))
            await process_batch(client, handler, [event])
            client.answer.assert_awaited_once_with(event['callback']['callback_id'])
            client.send.assert_awaited_once_with(55, 'Меню')
        client = SimpleNamespace(answer=AsyncMock(side_effect=MaxAPIError('unauthorized', status=401)), send=AsyncMock())
        handler = SimpleNamespace(handle=AsyncMock())
        with self.assertRaises(MaxAPIError):
            await process_batch(client, handler, [event])
        handler.handle.assert_not_awaited()


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL tests disabled')
class CallbackInterfaceTests(DatabaseFixture):
    async def link(self, user, sender=9001):
        links = AccountLinkService()
        request = await links.issue('telegram', str(user.id), 'max')
        await links.claim('max', str(sender), request['code'])
        return await links.confirm('telegram', str(user.id), request['id'])

    async def press(self, text, sender=9001, mid=None):
        event = message(sender, text)
        event['message']['body']['mid'] = mid or uuid4().hex
        return (await MaxHandler().handle(event))[1]

    async def test_project_navigation_labels_and_back_match_telegram(self):
        await self.link(self.manager)
        menu = await self.press('Проекты')
        self.assertEqual(menu.buttons, labels(ui.build_projects_menu_keyboard()))
        listing = await self.press(menu.buttons[0][0])
        self.assertEqual(listing.buttons, [[self.project.name], ['Назад']])
        card = await self.press(listing.buttons[0][0])
        self.assertEqual(card.buttons, labels(ui.build_project_card_keyboard(self.project.id, False)))
        self.assertNotIn('№', card)
        self.assertNotIn('Карточка проекта', str(card.buttons))
        self.assertEqual((await self.press(card.buttons[-1][0])).buttons, listing.buttons)
        self.assertEqual((await self.press(listing.buttons[-1][0])).buttons, menu.buttons)
        confirmation = await self.press(card.buttons[1][0])
        self.assertEqual(confirmation.buttons, [['Подтвердить'], ['Отмена']])
        self.assertIn('Проект:', await self.press(confirmation.buttons[1][0]))
        archived = await self.press(confirmation.buttons[0][0])
        self.assertEqual(archived.buttons, labels(ui.build_project_card_keyboard(self.project.id, True)))
        self.assertEqual((await self.press(archived.buttons[0][0])).buttons, card.buttons)

    async def test_employee_and_owner_menus_use_telegram_labels(self):
        await self.link(self.manager)
        await self.link(self.owner, 9002)
        menu = await self.press('Сотрудники')
        self.assertEqual(menu.buttons, labels(ui.build_employees_menu_keyboard()))
        employees = await self.press(menu.buttons[0][0])
        self.assertEqual(employees.buttons[0][0], self.employee.first_name)
        card = await self.press(employees.buttons[0][0])
        self.assertEqual(card.buttons, labels(ui.build_employee_card_keyboard(1)))
        companies = await self.press('Компании', 9002)
        self.assertEqual(companies.buttons[0][0], self.company.name)
        company = await self.press(companies.buttons[0][0], 9002)
        self.assertEqual(company.buttons, labels(ui.build_company_actions_keyboard(self.company.id, False, False, False)))
        members = await self.press(company.buttons[0][0], 9002)
        self.assertEqual(members.buttons[-1], ['Назад к карточке компании'])
        self.assertEqual((await self.press(members.buttons[-1][0], 9002)).buttons, company.buttons)

    async def test_rename_text_saves_immediately_and_duplicate_delivery_is_idempotent(self):
        await self.link(self.manager)
        active = await self.press('/admin_projects')
        card = await self.press(active.buttons[0][0])
        await self.press(card.buttons[0][0])
        result = await self.press('Ривер Дон', mid='rename-message')
        self.assertIn('Проект: Ривер Дон', result)
        self.assertNotIn('Подтвердить', str(result.buttons))
        repeated = await self.press('Ривер Дон', mid='rename-message')
        self.assertIn('Проект: Ривер Дон', repeated)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM workspace_events WHERE entity_type='project' AND action='renamed'"), 1)

    async def test_foreign_callback_user_does_not_gain_owner_or_manager_rights(self):
        await self.link(self.owner, 9001)
        await self.link(self.employee, 9002)
        event = message(9002, MenuButton('Создать компанию', '/create_company'))
        event['message']['sender'] = {'user_id': 9001}
        before = await self.pool.fetchval('SELECT count(*) FROM companies')
        reply = (await MaxHandler().handle(event))[1]
        self.assertNotIn('Отправь название', reply)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM companies'), before)
        event = message(9002, MenuButton('Подтвердить', '/project_archive_yes ' + str(self.project.id)))
        await MaxHandler().handle(event)
        self.assertEqual(await self.pool.fetchval('SELECT status FROM projects WHERE id=$1', self.project.id), 'active')

    async def test_money_selection_shows_names_and_callback_retries_issue_once(self):
        await self.link(self.manager)
        employees = await self.press('Выдать деньги')
        self.assertEqual(employees.buttons[0][0], self.employee.first_name)
        projects = await self.press(employees.buttons[0][0])
        self.assertEqual(projects.buttons[0][0], self.project.name)
        self.assertNotIn('заявка №', str(projects.buttons))
        await self.press(projects.buttons[0][0])
        await self.press('100')
        confirm = await self.press('Закупка')
        self.assertEqual(confirm.buttons[0], ['Выдать'])
        event = message(9001, confirm.buttons[0][0])
        for _ in range(2):
            self.assertIn('создана', (await MaxHandler().handle(event))[1])
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM advances'), 1)

    async def test_project_documents_are_available_and_scoped(self):
        from app.adapters.telegram.documents import DocumentService
        await self.link(self.manager)
        await DocumentService().save_document(self.employee, self.project, 'text', self.document, upload_id='callback-project-doc')
        active = await self.press('/admin_projects')
        card = await self.press(active.buttons[0][0])
        docs = await self.press(card.buttons[2][0])
        self.assertIn('Vendor', docs)
        self.assertEqual(docs.buttons, [['Назад']])
        self.assertEqual((await self.press(docs.buttons[0][0])).buttons, card.buttons)
        await self.link(self.employee, 9002)
        reply = await self.press(MenuButton('Документы проекта', '/project_documents ' + str(self.project.id)), 9002)
        self.assertNotIn('Vendor', reply)

"""Favoritos equivalentes, cliques repetidos e isolamento entre pessoas."""
import tempfile
import unittest
from pathlib import Path

from jobhunter import providers
from jobhunter.storage import Store


class FavoriteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'qa.sqlite')
        self.owner = self.store.register('QA Owner', 'owner@example.org', 'fictitious-strong-password')['id']
        self.member = self.store.register('QA Member', 'member@example.org', 'fictitious-strong-password')['id']
        self.aliases = []
        for source in ['Jooble', 'Google']:
            job = providers.make_job('Production Engineer', 'Example', 'Curitiba', f'https://example.org/{source}', source, country='BR')
            self.store.start_search(source, {}, self.owner)
            self.store.finish_search(source, {'jobs': [job]}, user_id=self.owner)
            self.aliases.append(self.store.search(source, self.owner)['jobs'][0])

    def tearDown(self):
        self.temp.cleanup()

    def test_equivalent_sources_form_one_favorite_and_either_alias_removes_it(self):
        for job in self.aliases:
            self.store.favorite(job, user_id=self.owner)
        self.assertEqual(len(self.store.favorites(self.owner)), 1)
        self.store.favorite({'id': self.aliases[0]['id']}, remove=True, user_id=self.owner)
        self.assertEqual(self.store.favorites(self.owner), [])

    def test_repeated_save_and_remove_are_idempotent_after_restart(self):
        for _ in range(3):
            self.store.favorite(self.aliases[0], user_id=self.owner)
        restarted = Store(self.store.path)
        self.assertEqual(len(restarted.favorites(self.owner)), 1)
        for _ in range(3):
            restarted.favorite(self.aliases[0], remove=True, user_id=self.owner)
        self.assertEqual(restarted.favorites(self.owner), [])

    def test_removing_a_shared_identifier_never_changes_another_accounts_favorite(self):
        self.store.favorite(self.aliases[0], user_id=self.owner)
        self.store.favorite(self.aliases[0], user_id=self.member)
        self.store.favorite(self.aliases[0], remove=True, user_id=self.member)
        self.assertEqual(len(self.store.favorites(self.owner)), 1)
        self.assertEqual(self.store.favorites(self.member), [])


if __name__ == '__main__':
    unittest.main()

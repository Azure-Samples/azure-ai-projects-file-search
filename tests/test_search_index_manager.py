# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license.
# See LICENSE file in the project root for full license information.
import csv
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from azure.identity.aio import DefaultAzureCredential

from search_index_manager import SearchIndexManager
from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models._enums import ConnectionType
from azure.core.exceptions import HttpResponseError

from ddt import ddt, data


class MockAsyncIterator:

    def __init__(self, list_data):
        assert list_data and isinstance(list_data, list)
        self._data = list_data

    async def __aiter__(self):
        for dt in self._data:
            yield dt


@ddt
class TestSearchIndexManager(unittest.IsolatedAsyncioTestCase):
    """Tests for the RAG helper."""

    # INPUT_DIR = os.path.join(
    #            os.path.dirname(os.path.dirname(__file__)), 'data')
    INPUT_DIR = os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.dirname(__file__)))), 'data_')
    EMBEDDINGS_FILE = os.path.join(INPUT_DIR, 'embeddings.csv')

    @classmethod
    def setUpClass(cls) -> None:
        super(TestSearchIndexManager, cls).setUpClass()

    def setUp(self) -> None:
        self.search_endpoint = os.environ["SEARCH_ENDPOINT"]
        self.index_name = "test_index"
        self.embed_key = os.environ['EMBED_API_KEY']
        self.model = "text-embedding-3-small"
        unittest.TestCase.setUp(self)

    async def test_create_delete_mock(self):
        """Test that if index is deleteed the appropriate error is raised."""
        mock_ix_client = AsyncMock()
        mock_aenter = AsyncMock()
        with patch(
            'search_index_manager.SearchIndexClient',
                return_value=mock_ix_client):
            mock_ix_client.__aenter__.return_value = mock_aenter
            rag = self._get_mock_rag(AsyncMock())
            self.assertTrue(await rag.create_index())
            mock_aenter.create_index.assert_called_once()
            mock_aenter.get_index.assert_not_called()
            mock_aenter.create_index.reset_mock()
            mock_aenter.create_index.side_effect = HttpResponseError(
                'Mock http error')
            self.assertFalse(await rag.create_index())
            mock_aenter.create_index.assert_called_once()
            mock_aenter.get_index.assert_called_once()
            with self.assertRaisesRegex(HttpResponseError, 'Mock http error'):
                await rag.create_index(raise_on_error=True)
            await rag.delete_index()
            mock_aenter.create_index.side_effect = ValueError(
                'Mock value error')
            with self.assertRaisesRegex(ValueError, 'Mock value error'):
                await rag.create_index()

            mock_aenter.delete_index.assert_called_once()
            with self.assertRaisesRegex(
                    ValueError,
                    "Unable to perform the operation "
                    "as the index is absent.+"):
                await rag.delete_index()

    async def test_exception_no_dinmensions(self):
        """Test the exception shown if no dimensions were provided."""
        rag = SearchIndexManager(
            endpoint=self.search_endpoint,
            credential=AsyncMock(),
            index_name=self.index_name,
            dimensions=None,
            model=self.model,
            deployment_name="mock_embedding_model",
            embedding_endpoint="",
            embedding_client=AsyncMock(),
            embed_api_key=self.embed_key,
        )
        with self.assertRaisesRegex(
          ValueError, "No embedding dimensions were provided.+"):
            await rag.create_index(vector_index_dimensions=None)

    async def test_exception_different_dimmensions(self):
        """Test the exception shown if dimensions
        and dinensions_override are different."""
        rag = SearchIndexManager(
            endpoint=self.search_endpoint,
            credential=AsyncMock(),
            index_name=self.index_name,
            dimensions=41,
            model=self.model,
            embedding_client=AsyncMock(),
            deployment_name=self.model,
            embedding_endpoint=self.search_endpoint,
            embed_api_key=self.embed_key,
        )
        with self.assertRaisesRegex(
                ValueError,
                "vector_index_dimensions is different "
                "from dimensions provided to constructor."):
            await rag.create_index(vector_index_dimensions=42)

    #@unittest.skip("Only for live tests.")
    async def test_e2e(self):
        """Run search end to end."""
        async with DefaultAzureCredential() as creds:
            async with AIProjectClient.from_connection_string(
                credential=creds,
                conn_str=os.environ["AZURE_AIPROJECT_CONNECTION_STRING"],
            ) as project:
                aoai_connection = await project.connections.get_default(
                    connection_type=ConnectionType.AZURE_OPEN_AI,
                    include_credentials=True)
                self.assertIsNotNone(aoai_connection)
                rag = SearchIndexManager(
                    endpoint=self.search_endpoint,
                    credential=creds,
                    index_name=self.index_name,
                    dimensions=100,
                    model=self.model,
                    deployment_name=self.model,
                    embedding_endpoint=aoai_connection.endpoint_url,
                    embed_api_key=aoai_connection.key,
                )
                self.assertTrue(await rag.create_index(raise_on_error=True))
                await rag.upload_documents(
                    os.path.join(
                        os.path.dirname(
                            os.path.dirname(
                                __file__)), 'data', 'embeddings.csv'))

                result = await rag.search(
                    "What is the temperature rating "
                    "of the cozynights sleeping bag?")
                result_semantic = await rag.semantic_search(
                    "What is the temperature rating "
                    "of the cozynights sleeping bag?")
                await rag.delete_index()
                await rag.close()
                self.assertTrue(bool(result), "The regular search is empty.")
                self.assertTrue(bool(result_semantic), "The semantic search is empty.")

    async def test_life_cycle_mock(self):
        """Test create, upload, search and delete"""
        mock_ix_client = AsyncMock()
        mock_aenter = AsyncMock()
        mock_serch_client = AsyncMock()
        mock_serch_client.search.return_value = MockAsyncIterator([
            {'token': 'a', 'document_reference': 'a.txt'},
            {'token': 'b', 'document_reference': 'b.txt'}
        ])
        with patch(
            'search_index_manager.SearchIndexClient',
                return_value=mock_ix_client):
            with patch(
                'search_index_manager.SearchClient',
                    return_value=mock_serch_client):
                mock_ix_client.__aenter__.return_value = mock_aenter
                rag = self._get_mock_rag(AsyncMock())
                self.assertTrue(await rag.create_index())

                # Upload documents.
                await rag.upload_documents(
                    TestSearchIndexManager.EMBEDDINGS_FILE)
                mock_serch_client.upload_documents.assert_called_once()

                search_result = await rag.search('test')
                mock_serch_client.search.assert_called_once()
                self.assertEqual(search_result,
                                 "a, source: a.txt\n------\nb, source: b.txt")

    @data(2, 4)
    async def test_build_embeddings_file_mock(self, sentences_per_embedding):
        """Use this test to build
        the new embeddings file in the data directory."""
        embedding_client = AsyncMock()
        embedding_client.embed.retun_value = {'data': [[0, 0], [1, 1], [
            2, 2]] if sentences_per_embedding == 4 else [[0, 0], [1, 1]]}
        rag = SearchIndexManager(
            endpoint=self.search_endpoint,
            credential=AsyncMock(),
            index_name=self.index_name,
            dimensions=2,
            model=self.model,
            deployment_name=self.model,
            embedding_endpoint=self.search_endpoint,
            embed_api_key=self.embed_key,
            embedding_client=embedding_client
        )
        sentences = [
            f"This is {v} sentence" for v in [
                'first', 'second', 'third', 'forth', 'fifth']]
        with tempfile.TemporaryDirectory() as d:
            data = ' '.join(sentences)
            input_file = os.path.join(d, 'input.csv')
            with open(input_file, 'w') as f:
                f.write(data)
            out_file = os.path.join(d, 'embeddings.csv')
            await rag.build_embeddings_file(
                input_directory=input_file,
                output_file=out_file,
                sentences_per_embedding=sentences_per_embedding
            )
            index = 1
            with open(out_file, newline='') as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    self.assertEqual(
                        ' '.join(
                            sentences[
                                index * sentences_per_embedding: (
                                    index + 1) * sentences_per_embedding]))
                    self.assertListEqual(
                        json.loads(
                            row['embedding']), [
                            index, index])
                    self.assertEqual(row['document_reference'], 'input.csv')
                    index += 1

    @unittest.skip("Only for live tests.")
    async def test_build_embeddings_file(self):
        """Use this test to build the new
        embeddings file in the data directory."""
        async with DefaultAzureCredential() as creds:
            async with AIProjectClient.from_connection_string(
                credential=creds,
                conn_str=os.environ["AZURE_AIPROJECT_CONNECTION_STRING"],
            ) as project:
                aoai_connection = await project.connections.get_default(
                    connection_type=ConnectionType.AZURE_OPEN_AI)
                self.assertIsNotNone(aoai_connection)
                async with (
                  await project.inference.get_embeddings_client()) as embed:
                    rag = SearchIndexManager(
                        endpoint=self.search_endpoint,
                        credential=creds,
                        index_name=self.index_name,
                        dimensions=100,
                        model=self.model,
                        deployment_name=self.model,
                        embedding_endpoint=aoai_connection.endpoint_url,
                        embed_api_key=self.embed_key,
                        embedding_client=embed
                    )
                    await rag.build_embeddings_file(
                        input_directory=TestSearchIndexManager.INPUT_DIR,
                        output_file=TestSearchIndexManager.EMBEDDINGS_FILE,
                    )

    @unittest.skip("Only for live tests.")
    async def test_get_or_create(self):
        """Test index_name creation."""
        async with DefaultAzureCredential() as cred:
            self.AssertTrue(await SearchIndexManager.create_index(
                endpoint=self.search_endpoint,
                credential=cred,
                index_name=self.index_name,
                dimensions=100))
            self.AssertFalse(await SearchIndexManager.create_index(
                endpoint=self.search_endpoint,
                credential=cred,
                index_name=self.index_name,
                dimensions=100500))

    def _get_mock_rag(self, embedding_client):
        """Return the mock RAG """
        return SearchIndexManager(
            endpoint=self.search_endpoint,
            credential=AsyncMock(),
            index_name=self.index_name,
            dimensions=100,
            model="mock_embedding_model",
            deployment_name="mock_embedding_model",
            embedding_client=embedding_client,
            embedding_endpoint="",
            embed_api_key=self.embed_key

        )


if __name__ == "__main__":
    # import sys;sys.argv = ['', 'Test.testName']
    unittest.main()

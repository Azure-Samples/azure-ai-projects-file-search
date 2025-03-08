from typing import Any, Dict, Optional

import csv
import glob
import json
import os
import time

from azure.core.credentials_async import AsyncTokenCredential
from azure.search.documents.aio import AsyncSearchItemPaged, SearchClient 
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.core.exceptions import HttpResponseError
from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticSearch,
    SemanticConfiguration,
    SemanticPrioritizedFields,
    SemanticField,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizableTextQuery



class SearchIndexManager:
    """
    The class for searching of context for user queries.

    :param endpoint: The search endpoint to be used.
    :param credential: The credential to be used for the search.
    :param index_name: The name of an index to get or to create.
    :param dimensions: The number of dimensions in the embedding. Set this parameter only if
                       embedding model accepts dimensions parameter.
    :param model: The embedding model to be used,
                  must be the same as one use to build the file with embeddings.
    :param deployment_name: The name of the embedding deployment.
    :param embeddings_endpoint: The the endpoint used for embedding.
    :param embed_api_key: The api key used by the embedding resource.
    :param embedding_client: The embedding client, used t build the embedding. Needed only
                             to create embedding file. Not used in inference time.
    """
    
    MIN_DIFF_CHARACTERS_IN_LINE = 5
    MIN_LINE_LENGTH = 5
    
    _SEMANTIC_CONFIG = "semantic_search"
    _EMBEDDING_CONFIG = "embedding_config"
    _VECTORIZER = "search_vectorizer"


    def __init__(
            self,
            endpoint: str,
            credential: AsyncTokenCredential,
            index_name: str,
            dimensions: Optional[int],
            model: str,
            deployment_name: str,
            embedding_endpoint: str, 
            embed_api_key: str,
            embedding_client: Optional[Any] = None
        ) -> None:
        """Constructor."""
        self._dimensions = dimensions
        self._index_name = index_name
        self._embeddings_endpoint = embedding_endpoint
        self._endpoint = endpoint
        self._credential = credential
        self._index = None
        self._embedding_model = model
        self._embedding_deployment = deployment_name
        self._embed_api_key = embed_api_key
        self._client = None
        self._embedding_client = embedding_client

    def _get_client(self):
        """Get search client if it is absent."""
        if self._client is None:
            self._client = SearchClient(
                endpoint=self._endpoint, index_name=self._index.name, credential=self._credential)
        return self._client
    
    async def upload_documents(self, embeddings_file: str) -> None:
        """
        Upload the embeggings file to index search.

        :param embeddings_file: The embeddings file to upload.
        """
        self._raise_if_no_index()
        documents = []
        index = 0
        with open(embeddings_file, newline='') as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                documents.append(
                    {
                        'embedId': str(index),
                        'token': row['token'],
                        'embedding': json.loads(row['embedding']),
                        'document_reference': row['document_reference'] 
                    }
                )
                index += 1
        await self._get_client().upload_documents(documents)

    def _raise_if_no_index(self) -> None:
        """
        Raise the exception if the index was not created.

        :raises: ValueError
        """
        if self._index is None:
            raise ValueError(
                "Unable to perform the operation as the index is absent. "
                "To create index please call create_index")

    async def delete_index(self):
        """Delete the index from vector store."""
        self._raise_if_no_index()
        async with SearchIndexClient(endpoint=self._endpoint, credential=self._credential) as ix_client:
            await ix_client.delete_index(self._index.name)
        self._index = None

    def _check_dimensions(self, vector_index_dimensions: Optional[int] = None) -> int:
        """
        Check that the dimensions are set correctly.

        :return: the correct vector index dimensions.
        :raises: Value error if both dimensions of embedding model and vector_index_dimensions are not set
                 or both of them set and they do not equal each other.
        """
        if vector_index_dimensions is None:
            if self._dimensions is None:
                raise ValueError(
                    "No embedding dimensions were provided in neither dimensions in the constructor nor in vector_index_dimensions"
                    "Dimensions are needed to build the search index, please provide the vector_index_dimensions.")
            vector_index_dimensions = self._dimensions
        if self._dimensions is not None and vector_index_dimensions != self._dimensions:
            raise ValueError("vector_index_dimensions is different from dimensions provided to constructor.")
        return vector_index_dimensions

    async def _format_search_results(self, response: AsyncSearchItemPaged[Dict]) -> str:
        """
        Format the output of search.

        :param response: The search results.
        :return: The formatted response string.
        """
        results = [f"{result['token']}, source: {result['document_reference']}" async for result in response]
        return "\n------\n".join(results)

    async def semantic_search(self, message: str) -> str:
        """
        Perform the semantic search on the search resource.

        :param message: The customer question.
        :return: The context for the question.
        """
        self._raise_if_no_index()
        response = await self._get_client().search(
            search_text=message,
            query_type="semantic",
            search_fields=['token', 'document_reference'],
            semantic_configuration_name=SearchIndexManager._SEMANTIC_CONFIG,
        )
        return await self._format_search_results(response)
        

    async def search(self, message: str) -> str:
        """
        Search the message in the vector store.

        :param message: The customer question.
        :return: The context for the question.
        """
        self._raise_if_no_index()
        vector_query = VectorizableTextQuery(
            text=message,
            k_nearest_neighbors=5,
            fields="embedding"
        )
        response = await self._get_client().search(
            vector_queries=[vector_query],
            select=['token', 'document_reference'],
        )
        # This lag is necessary, despite it is not described in documentation.
        time.sleep(1)
        return await self._format_search_results(response)

    async def create_index(
        self,
        vector_index_dimensions: Optional[int] = None,
        raise_on_error: bool=False
        ) -> bool:
        """
        Create index or return false if it already exists.

        :param vector_index_dimensions: The number of dimensions in the vector index. This parameter is
               needed if the embedding parameter cannot be set for the given model. It can be
               figured out by loading the embeddings file, generated by build_embeddings_file,
               loading the contents of the first row and 'embedding' column as a JSON and calculating
               the length of the list obtained.
               Also please see the embedding model documentation
               https://platform.openai.com/docs/models#embeddings
        :param raise_on_error: Raise if index creation was not successful.
        :return: True if index was created, False otherwise.
        :raises: Value error if both dimensions of embedding model and vector_index_dimensions are not set
                 or both of them are set and they do not equal each other.
        """
        vector_index_dimensions = self._check_dimensions(vector_index_dimensions)
        try:
            self._index = await self._index_create(vector_index_dimensions)
            return True
        except HttpResponseError:
            if raise_on_error:
                raise
            async with SearchIndexClient(endpoint=self._endpoint, credential=self._credential) as ix_client:
                self._index = await ix_client.get_index(self._index_name)
            return False
        
    async def _index_create(self, vector_index_dimensions: int) -> SearchIndex:
        """
        Create the index.

        :param vector_index_dimensions: The number of dimensions in the vector index. This parameter is
               needed if the embedding parameter cannot be set for the given model. It can be
               figured out by loading the embeddings file, generated by build_embeddings_file,
               loading the contents of the first row and 'embedding' column as a JSON and calculating
               the length of the list obtained.
               Also please see the embedding model documentation
               https://platform.openai.com/docs/models#embeddings
        :return: The newly created search index.
        """
        async with SearchIndexClient(endpoint=self._endpoint, credential=self._credential) as ix_client:
            fields = [
                SimpleField(name="embedId", type=SearchFieldDataType.String, key=True),
                SearchField(
                    name="embedding",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    vector_search_dimensions=vector_index_dimensions,
                    searchable=True,
                    vector_search_profile_name=SearchIndexManager._EMBEDDING_CONFIG
                ),
                SearchField(name="token", searchable=True, type=SearchFieldDataType.String, hidden=False),
                SearchField(name="document_reference", type=SearchFieldDataType.String, hidden=False),
            ]
            vector_search = VectorSearch(
                profiles=[
                    VectorSearchProfile(
                        name=SearchIndexManager._EMBEDDING_CONFIG,
                        algorithm_configuration_name="embed-algorithms-config",
                        vectorizer_name=SearchIndexManager._VECTORIZER
                    )
                ],
                algorithms=[HnswAlgorithmConfiguration(name="embed-algorithms-config")],
                vectorizers=[
                    AzureOpenAIVectorizer(
                        vectorizer_name=SearchIndexManager._VECTORIZER,
                        parameters=AzureOpenAIVectorizerParameters(
                            resource_url=self._embeddings_endpoint,
                            deployment_name=self._embedding_deployment,
                            api_key=self._embed_api_key,
                            model_name=self._embedding_model
                        )
                    )
                ]
            )
            semantic_search = SemanticSearch(
                default_configuration_name=SearchIndexManager._SEMANTIC_CONFIG,
                configurations=[
                    SemanticConfiguration(
                        name=SearchIndexManager._SEMANTIC_CONFIG,
                        prioritized_fields=SemanticPrioritizedFields(
                            title_field=SemanticField(field_name="document_reference"),
                            content_fields=[
                                SemanticField(field_name="token"),
                            ]
                        )
                    )
                ] 
            )
            search_index = SearchIndex(
                name=self._index_name,
                fields=fields,
                vector_search=vector_search,
                semantic_search=semantic_search)
            new_index = await ix_client.create_index(search_index)
        return new_index
        

    async def build_embeddings_file(
            self,
            input_directory: str,
            output_file: str,
            sentences_per_embedding: int=4,
            ) -> None:
        """
        In this method we do lazy loading of nltk and download the needed data set to split

        document into tokens. This operation takes time that is why we hide import nltk under this
        method. We also do not include nltk into requirements because this method is only used
        during rag generation.
        :param dimensions: The number of dimensions in the embeddings. Must be the same as
               the one used for SearchIndexManager creation.
        :param input_directory: The directory with the embedding files.
        :param output_file: The file csv file to store embeddings.
        :param embeddings_client: The embedding client, used to create embeddings. 
                Must be the same as the one used for SearchIndexManager creation.
        :param sentences_per_embedding: The number of sentences used to build embedding.
        """
        import nltk
        nltk.download('punkt')
        
        from nltk.tokenize import sent_tokenize
        # Split the data to sentence tokens.
        sentence_tokens = []
        references = []
        globs = glob.glob(input_directory + '/*.md', recursive=True)
        index = 0
        for fle in globs:
            with open(fle) as f:
                for line in f:
                    line = line.strip()
                    # Skip non informative lines.
                    if len(line) < SearchIndexManager.MIN_LINE_LENGTH or len(set(line)) < SearchIndexManager.MIN_DIFF_CHARACTERS_IN_LINE:
                        continue
                    for sentence in sent_tokenize(line):
                        if index % sentences_per_embedding == 0:
                            sentence_tokens.append(sentence)
                            references.append(os.path.split(fle)[-1])
                        else:
                            sentence_tokens[-1] += ' '
                            sentence_tokens[-1] += sentence
                        index += 1
        
        
        # For each token build the embedding, which will be used in the search.
        batch_size = 2000
        with open(output_file, 'w') as fp:
            writer = csv.DictWriter(fp, fieldnames=['token', 'embedding', 'document_reference'])
            writer.writeheader()
            for i in range(0, len(sentence_tokens), batch_size):
                emedding = (await self._embedding_client.embed(
                    input=sentence_tokens[i:i+min(batch_size, len(sentence_tokens))],
                    dimensions=self._dimensions,
                    model=self._embedding_model
                ))["data"]
                for token, float_data, reference in zip(sentence_tokens, emedding, references):
                    writer.writerow({
                        'token': token,
                        'embedding': json.dumps(float_data['embedding']),
                        'document_reference': reference})

    async def close(self):
        """Close the closeable resources, associated with SearchIndexManager."""
        if self._client:
            await self._client.close()

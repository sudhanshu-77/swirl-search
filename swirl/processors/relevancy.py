'''
@author:     Sid Probstein
@contact:    sidprobstein@gmail.com
'''

from math import sqrt
from statistics import mean, median

from django.conf import settings

# to do: detect language and load all stopwords? P1
from swirl.nltk import stopwords_en, word_tokenize, sent_tokenize
from swirl.processors.utils import clean_string, stem_string, match_all, match_any, highlight_list, remove_tags
from swirl.spacy import nlp
from swirl.processors.processor import PostResultProcessor

#############################################    
#############################################    

class CosineRelevancyProcessor(PostResultProcessor):

    # This processor loads a set of saved results, scores them, and updates the results
    type = 'CosineRelevancyPostResultProcessor'

    ############################################

    def process(self):

        RELEVANCY_CONFIG = settings.SWIRL_RELEVANCY_CONFIG
        
        # prep query string
        query = clean_string(self.search.query_string_processed).strip()
        query_list = query.strip().split()

        # not list
        list_not = []
        updated_query = []
        # to do: this needs to be handled by a new QueryProcessor, also P1
        lower_query = ' '.join(query_list).lower()
        lower_query_list = lower_query.split()
        if 'not' in lower_query_list:
            updated_query = query_list[:lower_query_list.index('not')]
            list_not = query_list[lower_query_list.index('not')+1:]
        else:
            for q in query_list:
                if q.startswith('-'):
                    list_not.append(q[1:])
                else:
                    updated_query.append(q)
                # end if
            # end for
        # end if
        if updated_query:
            query = ' '.join(updated_query).strip()
            query_list = query.split()
        # end if
        query_len = len(query_list)
        query_nlp = nlp(query)

        # check for zero vector
        empty_query_vector = False
        if query_nlp.vector.all() == 0:
            empty_query_vector = True

        # check for stopword query
        query_without_stopwords = []
        for extract in query_list:
            if not extract in stopwords_en:
                query_without_stopwords.append(extract)
        if len(query_without_stopwords) == 0:
            self.error(f"query_string_processed is all stopwords!")
            # to do: handle more gracefully
            return self.results

        # fix for https://github.com/sidprobstein/swirl-search/issues/34
        query_stemmed_list = stem_string(clean_string(self.search.query_string_processed)).strip().split()

        updated = 0
        dict_lens = {}

        ############################################
        # PASS 1
        for results in self.results:
            ############################################
            # result set
            highlighted_json_results = []
            if not results.json_results:
                continue
            for result in results.json_results:
                ############################################
                # result item
                dict_score = {}
                dict_len = {}
                notted = ""
                for field in RELEVANCY_CONFIG:
                    if field in result:
                        # result_field is shorthand for item[field]
                        if type(result[field]) == list:
                            result[field] = result[field][0]
                        # prepare result field
                        result_field = clean_string(result[field]).strip()
                        result_field_nlp = nlp(result_field)
                        result_field_list = result_field.strip().split()
                        # not test
                        result_field_lower = ' '.join(result_field_list).lower()
                        result_field_lower_list = result_field_lower.split()
                        for t in list_not:
                            if t.lower() in result_field_lower_list:
                                notted = {field: t}
                                break
                        # field length
                        if field in dict_len:
                            self.warning("duplicate field?")
                        else:
                            dict_len[field] = len(result_field_list)
                        if field in dict_lens:
                            dict_lens[field].append(len(result_field_list))
                        else:
                            dict_lens[field] = []
                            dict_lens[field].append(len(result_field_list))
                        # fix for https://github.com/sidprobstein/swirl-search/issues/34
                        result_field_stemmed = stem_string(result_field)
                        result_field_stemmed_list = result_field_stemmed.strip().split()
                        if len(result_field_list) != len(result_field_stemmed_list):
                            self.error("len(result_field_list) != len(result_field_stemmed_list), highlighting errors may occur")
                        dict_score[field] = {}
                        extracted_highlights = []
                        match_stems = []
                        ###########################################
                        # query vs result_field
                        if match_any(query_stemmed_list, result_field_stemmed_list):  
                            qvr = 0.0                          
                            label = '_*'
                            if empty_query_vector or result_field_nlp.vector.all() == 0:
                                if len(result_field_list) == 0:
                                    qvr = 0.0
                                else:
                                    qvr = 0.3 + 1/3
                                # end if
                            else:
                                if len(sent_tokenize(result_field)) > 1:
                                    # by sentence, take highest
                                    max_similarity = 0.0
                                    for sent in sent_tokenize(result_field):
                                        result_sent_nlp = nlp(sent)
                                        qvs = query_nlp.similarity(result_sent_nlp)
                                        if qvs > max_similarity:
                                            max_similarity = qvs
                                    # end for
                                    qvr = max_similarity
                                    label = '_s*'
                                else:
                                    qvr = query_nlp.similarity(result_field_nlp)
                            # end if
                            if qvr >= float(settings.SWIRL_MIN_SIMILARITY):
                                dict_score[field]['_'.join(query_list)+label] = qvr
                        ############################################
                        # all, 2, 1 gram
                        p = 0
                        while p <= query_len - 1:
                            grams = [1]
                            if query_len == 2:
                                grams = [2,1]
                            if query_len > 2:
                                grams = [query_len,2,1]
                            for gram in grams:
                                if len(result_field_list) == 0:
                                    continue
                                # a slice can be 1 gram (if query is length 1)
                                query_slice_list = query_list[p:p+gram]
                                query_slice_len = len(query_slice_list)
                                if query_slice_len == 1:
                                    if query_slice_list[0] in stopwords_en:
                                        continue
                                if query_slice_len == 0:
                                    continue
                                query_slice_stemmed_list = query_stemmed_list[p:p+gram]
                                if '_'.join(query_slice_list) in dict_score[field]:
                                    continue
                                ####### MATCH
                                # iterate across all matches, match on stem; match_all returns a list of result_field_list indexes that match
                                match_list = match_all(query_slice_stemmed_list, result_field_stemmed_list)
                                if len(match_list) > settings.SWIRL_MAX_MATCHES:
                                    match_list = match_list[:settings.SWIRL_MAX_MATCHES-1]
                                qw = query_slice_list
                                if match_list:
                                    key = ''
                                    for match in match_list:
                                        extracted_match_list = result_field_list[match:match+len(query_slice_stemmed_list)]
                                        key = '_'.join(extracted_match_list)+'_'+str(match)
                                        rw = result_field_list[match-(gram*2)-1:match+query_slice_len+2+(gram*2)]
                                        dict_score[field][key] = 0.0
                                        ######## SIMILARITY vs WINDOW
                                        rw_nlp = nlp(' '.join(rw))
                                        if rw_nlp.vector.all() == 0:
                                            dict_score[field][key] = 0.31 + 1/3
                                        qw_nlp = nlp(' '.join(qw))
                                        if qw_nlp.vector.all() == 0:
                                            dict_score[field][key] = 0.32 + 1/3
                                        qw_nlp_sim = qw_nlp.similarity(rw_nlp)
                                        if qw_nlp_sim:
                                            if qw_nlp_sim >= float(settings.SWIRL_MIN_SIMILARITY):
                                                dict_score[field][key] = qw_nlp_sim
                                        if dict_score[field][key] == 0.0:
                                            del dict_score[field][key]
                                        ######### COLLECT MATCHES FOR HIGHLIGHTING
                                        for extract in extracted_match_list:
                                            if extract in extracted_highlights:
                                                continue
                                            extracted_highlights.append(extract)
                                        if '_'.join(query_slice_stemmed_list) not in match_stems:
                                            match_stems.append('_'.join(query_slice_stemmed_list))
                                    # end for
                                    # dict_score[field]['_highlight_hits'] = extracted_highlights
                                    # dict_score[field]['_matching_stems'] = match_stems
                            # end for
                            p = p + 1
                        # end while
                        if dict_score[field] == {}:
                            del dict_score[field]
                        ############################################
                        # highlight
                        result[field] = result[field].replace('*','')   # remove old
                        # fix for https://github.com/sidprobstein/swirl-search/issues/33
                        result[field] = highlight_list(remove_tags(result[field]), extracted_highlights)
                    # end if
                # end for field in RELEVANCY_CONFIG:
                if notted:
                    result['NOT'] = notted
                else:
                    result['dict_score'] = dict_score
                    result['dict_len'] = dict_len
            # end for result in results.json_results:
            # results.save()
        # end for results in self.results:
        ############################################
        # Compute field means
        dict_len_median = {}
        for field in dict_lens:
            dict_len_median[field] = mean(dict_lens[field])
        ############################################
        # PASS 2
        # score results by field, adjusting for field length
        for results in self.results:
            if not results.json_results:
                continue
            for result in results.json_results:
                result['swirl_score'] = 0.0
                # check for not
                if 'NOT' in result:
                    result['swirl_score'] = -1.0 + 1/3
                    result['explain'] = { 'NOT': result['NOT'] }
                    del result['NOT']
                    break
                # retrieve the scores and lens from pass 1
                if 'dict_score' in result:
                    dict_score = result['dict_score']
                    del result['dict_score']
                else:
                    self.warning(f"pass 2: result {results}: {result} has no dict_score")
                if 'dict_len' in result:
                    dict_len = result['dict_len']
                    del result['dict_len']
                else:
                    self.warning(f"pass 2: result {results}: {result} has no dict_len")
                # score the item 
                for f in dict_score:
                    if f in RELEVANCY_CONFIG:
                        weight = RELEVANCY_CONFIG[f]['weight']
                    for k in dict_score[f]:
                        if k.startswith('_'):
                            continue
                        if not dict_score[f][k]:
                            continue
                        if dict_score[f][k] >= float(settings.SWIRL_MIN_SIMILARITY):
                            len_adjust = float(dict_len_median[f] / dict_len[f])
                            rank_adjust = float(1 / sqrt(result['searchprovider_rank']))
                            # self.warning(f"len_adjust: {len_adjust}: {result}")
                            # to do: this should also include _s*
                            if k.endswith('_*') or k.endswith('_s*'):
                                result['swirl_score'] = result['swirl_score'] + (weight * dict_score[f][k]) * (len(k) * len(k))
                            else:
                                result['swirl_score'] = result['swirl_score'] + (weight * dict_score[f][k]) * (len(k) * len(k)) * len_adjust * rank_adjust
                        # end if
                    # end for
                # end for
                ####### explain
                result['explain'] = dict_score                
                updated = updated + 1
                # save highlighted version
                highlighted_json_results.append(result)
            # end for
            results.save()
        # end for
        ############################################

        self.results_updated = int(updated)
        
        return self.results_updated                
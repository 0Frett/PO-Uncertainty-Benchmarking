import numpy as np
import pickle
import math
import re
import os
from qa_struct import Single_Step_QA_Struct
from typing import Optional, Union, Dict, List
from llms_parallel import OpenAIModel_parallel
import logging
logger = logging.getLogger()

def npe_per_node(node:Single_Step_QA_Struct):
    actions_values = []
    for q_node in node.qa_matches:
        for a_node in q_node.children:
            logprobsum = 0
            for token in a_node.tokens_prob:
                logprobsum += token['top1Logprob']
            actions_values.append(logprobsum)
    assert len(actions_values) > 0
    node.npe = -np.mean(actions_values)

def lnpe_per_node(node:Single_Step_QA_Struct):
    actions_values = []
    for q_node in node.qa_matches:
        for a_node in q_node.children:
            logprobsum = 0
            tokennum = 0
            for token in a_node.tokens_prob:
                logprobsum += token['top1Logprob']
                tokennum += 1
            actions_values.append(logprobsum/tokennum)
    node.lnpe = -np.mean(actions_values)

def top2disparity_per_node(node:Single_Step_QA_Struct):
    actions_values = []
    for q_node in node.qa_matches:
        for a_node in q_node.children:
            disparity_sum = 0
            tokennum = 0
            for token in a_node.tokens_prob:
                disparity_sum += (token['top1Logprob']-token['top2Logprob'])
                tokennum += 1
            actions_values.append(disparity_sum/tokennum)
    node.top2disparity = -np.mean(actions_values)

def verbal_confidence_per_node(node:Single_Step_QA_Struct, model:OpenAIModel_parallel):
    success = 0
    total = 0
    predict = []
    for q_node in node.qa_matches:
        question = q_node.question
        for a_node in q_node.children:   
            tokens = a_node.tokens_prob
            answer = ""
            for t in tokens:
                answer += t['token']

            prompt = f"""
                    Given the math question and answer below, evaluate the answer.\n
                    Is the answer correct or wrong?\n
                    Q:{question}\n
                    A:{answer}\n
                    Output:(correct or wrong)
                    """
            gen = model.generate(prompt=prompt, num_return_sequences=5)
            incorrect = sum("wrong" in g.lower() for g in gen.text)
            hat = incorrect < 3
            predict.append(hat)
            if a_node.is_correct == hat:
                success += 1
            total += 1

    node.verb_conf = predict.count(True)/len(predict)
    node.verb_predict_performance = success / total

    print('verb_conf', node.verb_conf)
    print('verb_pp', node.verb_predict_performance)

def se_per_node(node:Single_Step_QA_Struct):
    pass

def spuq_per_node(node:Single_Step_QA_Struct):
    pass

def intra_sample_score_per_node(node:Single_Step_QA_Struct):
    pass

def fidelity_confidence_per_node(node:Single_Step_QA_Struct):
    pass

def calculate_entropy(values:list):
    if len(values) == 0:
        return 0.0
    total_count = len(values)
    value_counts = {}
    for value in values:
        if value in value_counts:
            value_counts[value] += 1
        else:
            value_counts[value] = 1
    entropy = 0.0
    for count in value_counts.values():
        probability = count / total_count
        if probability > 0:
            entropy -= probability * math.log2(probability)
    return entropy

def ensemble_approx_answer_uncertainty_per_node(node:Single_Step_QA_Struct):
    def collect_all_h_answers(node:Single_Step_QA_Struct):
        h_answers = []
        for q_node in node.qa_matches:
            for a_node in q_node.children:
                h_answers.append(a_node.answer)

        return h_answers
    
    def count_single_hypothesis_label_probs(values:list, answer_set:set):
        total = len(values)
        label_prob_dict = {}
        for ans in answer_set:
            label_prob_dict[ans] = values.count(ans)/total
        return label_prob_dict
        
    def update_node_ensemble_approx_uncertainty(node:Single_Step_QA_Struct, answer_set:set):
        entropy_for_each_hypothesis = []
        label_probs_of_each_hypothesis = {ans:[] for ans in answer_set}

        for q_node in node.qa_matches:
            h_nodes = [a_node.answer for a_node in q_node.children]
            prob_dict = count_single_hypothesis_label_probs(h_nodes, answer_set)
            for key, value in prob_dict.items():
                label_probs_of_each_hypothesis[key].append(value)
            entropy_for_each_hypothesis.append(calculate_entropy(h_nodes))
        
        # update node values
        node.ensemble_approx_answer_aleatoric_uncertainty = np.mean(entropy_for_each_hypothesis)
        hypotheses_average_label_probs = [
            np.mean(hypotheses_label_prob) for hypotheses_label_prob in label_probs_of_each_hypothesis.values()
        ]
        entropy = 0.0
        for probability in hypotheses_average_label_probs:
            if probability >0:
                entropy -= probability * math.log2(probability)
        node.ensemble_approx_answer_total_uncertainty = entropy
        node.ensemble_approx_answer_epistemic_uncertainty = (
            node.ensemble_approx_answer_total_uncertainty - node.ensemble_approx_answer_aleatoric_uncertainty
        )

    answer_set = set(collect_all_h_answers(root))
    update_node_ensemble_approx_uncertainty(root, answer_set)


def ensemble_approx_correctness_uncertainty_per_node(node:Single_Step_QA_Struct):
    def collect_all_h_correctness(node:Single_Step_QA_Struct):
        h_correctness = []
        for q_node in node.qa_matches:
            for a_node in q_node.children:
                h_correctness.append(a_node.is_correct)
        
        return h_correctness

    def update_node_ensemble_approx_uncertainty(node:Single_Step_QA_Struct):
        entropy_for_each_hypothesis = []
        correct_prob_for_each_hypothesis = []
        wrong_prob_for_each_hypothesis = []
        for q_node in node.qa_matches:
            h_nodes = [a_node.is_correct for a_node in q_node.children]
            correct_prob_for_each_hypothesis.append(h_nodes.count(True)/len(h_nodes))
            wrong_prob_for_each_hypothesis.append(h_nodes.count(False)/len(h_nodes))
            entropy_for_each_hypothesis.append(calculate_entropy(h_nodes))

        # update node values
        node.ensemble_approx_correctness_aleatoric_uncertainty = np.mean(entropy_for_each_hypothesis)
        hypotheses_average_label_probs = [
            np.mean(correct_prob_for_each_hypothesis), 
            np.mean(wrong_prob_for_each_hypothesis)
        ]
        entropy = 0.0
        for probability in hypotheses_average_label_probs:
            if probability > 0:
                entropy -= probability * math.log2(probability)
        node.ensemble_approx_correctness_total_uncertainty = entropy

        # print(node.correctness_total_uncertainty, node.ensemble_approx_correctness_total_uncertainty)
        #assert node.correctness_total_uncertainty == node.ensemble_approx_correctness_total_uncertainty
        node.ensemble_approx_correctness_epistemic_uncertainty = (
            node.ensemble_approx_correctness_total_uncertainty - node.ensemble_approx_correctness_aleatoric_uncertainty
        )

    node_correctness = collect_all_h_correctness(root)
    node.correct_ratio = node_correctness.count(True)/len(node_correctness)
    print('correct nodes :', node_correctness.count(True))
    print('wrong nodes :', node_correctness.count(False))
    update_node_ensemble_approx_uncertainty(root)


def load_node(filename):
    with open(filename, 'rb') as f:
        return pickle.load(f)

def save_node(root, filename):
    with open(filename, 'wb') as f:
        pickle.dump(root, f)

if __name__ == '__main__':
    llm = OpenAIModel_parallel(
        model='gpt-3.5-turbo',
        max_tokens=10,
        temperature=0.5,
    )
    qindices = [int(re.search(r'\d+', s).group()) for s in os.listdir('./output_nodes')][500:]
    node_nums = [i for i in range(1,6)]
    for idx in qindices:
        for num in node_nums:
            try:
                print(f"============{idx}-{num}===============")
                filename = f'./output_nodes/Q{idx}/node_{num}/node.pkl'
                root = load_node(filename=filename)
                verbal_confidence_per_node(node=root, model=llm)
                save_node(root=root, filename=filename)
            # try:
            #     print(f"============{idx}-{num}===============")
            #     filename = f'./output_nodes/Q{idx}/node_{num}/node.pkl'
            #     root = load_node(filename=filename)
            #     npe_per_node(node=root)
            #     lnpe_per_node(node=root)
            #     top2disparity_per_node(node=root)
            #     ensemble_approx_correctness_uncertainty_per_node(node=root)
            #     ensemble_approx_answer_uncertainty_per_node(node=root)
            #     verbal_confidence_per_node(node=root, model=llm)
            #     save_node(root=root, filename=filename)
            except:
                print("fail")
                continue



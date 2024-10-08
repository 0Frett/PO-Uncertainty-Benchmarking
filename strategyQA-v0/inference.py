import json
from typing import Generic, List, Dict, Tuple, Callable, Any, Union, Optional
from datasets import load_dataset
import copy
import pickle
import os
from collections import Counter
from llms_parallel import OpenAIModel_parallel, LlamaModel
from qa_struct import ReasoningNode
from utils import Single_Step_StrategyQAUtils
from tqdm import tqdm
import random
import re
from hard_qs import hard1, hard2, hard3, hard4, hard5

class Single_Step_gsm8k_Inference():
    def __init__(
        self, 
        language_model:Union[OpenAIModel_parallel, LlamaModel],
        model_name:str,
        sampling_num:int,
        perturb_num:int,
    ):
        with open("./data/strategyqa_test.json", 'r') as f:
            dataset = json.load(f)
        self.full_dataset = dataset
        with open("./prompts/prompt.json", 'r') as f:
            prompt_pool = json.load(f)
        self.prompt_pool = prompt_pool
        self.language_model = language_model
        self.sampling_num = sampling_num
        self.perturb_num = perturb_num
        self.model_name = model_name

    def sample_prompt(self, num_shot:int = 4):
        prompt_list = random.sample(self.prompt_pool['cot_pool'], 4)
        example = "\n\n".join(prompt_list)
        self.prompt_pool['few_shot_examples'] = example

    
    def run_inference(self, start_idx:int, end_idx:int):
        print("data num", len(list(self.full_dataset)))
        self.dataset = list(self.full_dataset)[start_idx:end_idx]
        for i, example in enumerate(
            tqdm(
                self.dataset,
                total=start_idx + len(self.dataset),
                initial=start_idx,
                desc=f"StrategyQA_q{start_idx}~{end_idx}"
            )
        ):
            self.sample_prompt()
            node_utils = Single_Step_StrategyQAUtils(
                prompt_pool=self.prompt_pool,
                language_model=self.language_model,
                problem=example['question']
            )

            true_answer = str(example['answer'])
            print('true-answer:', true_answer)
            
            node = ReasoningNode(
                sampling_num=self.sampling_num,
                perturb_num=self.perturb_num,
                utils=node_utils,
                truth=true_answer
            ).run_algo()
            
            # save node
            os.makedirs(f'./output_nodes/{self.model_name}', exist_ok=True)
            save_dir = f'./output_nodes/{self.model_name}/Q{start_idx+i}'
            os.makedirs(save_dir, exist_ok=True)
            save_dir += f'/node_{len(os.listdir(save_dir))+1}'
            os.makedirs(save_dir, exist_ok=True)
            filename = f'{save_dir}/node.pkl'
            with open(filename, 'wb') as f:
                pickle.dump(node, f)


if __name__ == '__main__':
    # args
    sampling_num = 10
    perturb_num = 5
    temperature = 0.6
    modelname = 'llama' #'gpt-3.5-turbo'

    print(f'sampling_num:{sampling_num}\nperturb_num:{perturb_num}\ntemperature:{temperature}')

    have_idxs = [int(re.search(r'\d+', s).group()) for s in os.listdir(f'./output_nodes/{modelname}/')]
    if modelname == 'llama':
        llm = LlamaModel(
            model='meta-llama/Meta-Llama-3.1-8B-Instruct',
            max_tokens=500,
            temperature=temperature,
        )
    if modelname == 'gpt-3.5-turbo':
        llm = OpenAIModel_parallel(
            model=modelname,
            max_tokens=500,
            temperature=temperature,
        )
    
    q_idx = have_idxs
    for idx in q_idx:
        Single_Step_gsm8k_Inference(
            language_model=llm,
            model_name=modelname,
            sampling_num=sampling_num,
            perturb_num=perturb_num
        ).run_inference(start_idx=idx, end_idx=idx+1)

    # llm.usage()




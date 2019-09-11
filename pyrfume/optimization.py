import random

import numpy as np
import pandas as pd
from deap import base, creator, tools, algorithms


class OdorantSetOptimizer:
    def __init__(self, library, n_desired, weights=None, fitness=None,
                 n_gen=300, mu=100, lamda=200, p_cx=0.4, p_mut=0.4):
        """
        params:
            library: A pandas dataframe containing odorants and their
                     attributes. The index should contain chemical identifiers
                     (e.g. CIDs). The column names should be attributes,
                     e.g. molecular weight, price, etc.  They can also be
                     descriptors.
            n_desired: The site of the set of odorants desired from this
                       library.
            weights: A list of 3-tuples each containing the name of a weight,
                     a method to apply to the library dataframe, and a weight
                     to apply to the function's output.
        """

        # Turn all constructor arguments into attributes
        for key, value in locals().items():
            setattr(self, key, value)

        if self.fitness is None:
            self.fitness = BetterFitness

        # weights_dict = OrderedDict([
#                    ('abs_cost', -7.0),  # Total absolute cost
#                    ('rel_cost', -1.0),  # Average relative cost/mol
#                    ('coverage_hd', +8.0),  # Total coverage of Haddad space
#                    ('coverage_sz', +8.0),  # Total coverage of Snitz space
#                    ('intensity', +5.0),  # Average odorant intensity
#                    ('fame', +1.0),  # Average odorant fame
#                    #('count', -0.01), # Total number of odorants
        #                   ])

        weight_names, weight_functions, weight_values = zip(*self.weights)

        # Number of available odorants
        self.library_size = self.library.shape[0]

        # Odorant set cannot cost more than this amount
        # MAX_COST = 3000

        creator.create("Fitness", self.fitness, weights=weight_values)
        creator.create("Individual", set, fitness=creator.Fitness)

        self.toolbox = base.Toolbox()

        # Not sure what this does, but I think it says that item
        # attributes are random?
        self.toolbox.register("random_set", random.sample,
                              range(self.library_size), self.n_desired)

        # Says that an individual has something to do with attr_item,
        # and has initial size INITIAL_SET_SIZE
        self.toolbox.register("individual", tools.initIterate,
                              creator.Individual, self.toolbox.random_set)

        # Says that the population is just a list of individuals
        self.toolbox.register("population", tools.initRepeat, list,
                              self.toolbox.individual)
        self.toolbox.register("evaluate", self.eval_individual)
        self.toolbox.register("mate", self.crossover)
        self.toolbox.register("mutate", self.mutate)
        self.toolbox.register("select", tools.selBest)

    def eval_individual(self, individual):
        """Evaluate the fitness of the odorant set"""
        fitness = []
        for col_name, func_name, value in self.weights:
            if isinstance(func_name, str):
                f = getattr(self, 'eval_%s' % func_name)
                component = f(individual, col_name)
            else:
                f = func_name
                component = f(individual)
            fitness.append(component)
        return fitness

    def crossover(self, ind1, ind2):
        """Apply a crossover operation on input sets."""
        union = ind1 | ind2
        x1 = random.sample(union, self.n_desired)
        x2 = random.sample(union, self.n_desired)
        ind1.clear()
        ind1.update(x1)
        ind2.clear()
        ind2.update(x2)
        return ind1, ind2

    def mutate(self, individual):
        """Mutation that pops or add some elements."""
        N_MUTATIONS = 1
        available = list(set(range(self.library_size)).difference(individual))
        to_remove = random.sample(list(individual), N_MUTATIONS)
        to_add = random.sample(available, N_MUTATIONS)
        individual ^= set(to_remove)
        individual |= set(to_add)
        return individual

    def run(self, pop=None, hof=None):
        self.pop = pop if pop else self.toolbox.population(n=self.mu)
        if hof is None:
            self.hof = tools.HallOfFame(self.n_gen)
        self.stats = tools.Statistics(lambda ind: ind.fitness.values)
        self.stats.register("avg", lambda x: np.mean(x, axis=0))
        # stats.register("avg", lambda x: np.mean(x, axis=0))
        # stats.register("std", lambda x: np.std(x, axis=0).round(1))
        # stats.register("min", lambda x: np.min(x, axis=0).round(1))
        # stats.register("max", lambda x: np.max(x, axis=0).round(1))

        def best(x):
            weight_names, weight_functions, weight_values = zip(*self.weights)
            scores = [np.dot(self.hof.keys[i].values, weight_values)
                      for i in range(len(self.hof))]
            i = np.argmax(scores)
            return np.array([scores[i]] + list(self.hof.keys[i].values))

        self.stats.register("best", best)

        f = algorithms.eaMuPlusLambda
        self.pop, self.logbook = f(self.pop, self.toolbox, self.mu,
                                   self.lamda, self.p_cx, self.p_mut,
                                   self.n_gen, self.stats, halloffame=self.hof)

        return self.pop, self.stats, self.hof, self.logbook

    def eval_mean(self, individual, column):
        return self.library.iloc[list(individual)][column].mean()

    def eval_sum(self, individual, column):
        return self.library.iloc[list(individual)][column].sum()


class BetterFitness(base.Fitness):
    def __le__(self, other):
        return sum(self.wvalues) <= sum(other.wvalues)

    def __lt__(self, other):
        return sum(self.wvalues) < sum(other.wvalues)


if __name__ == '__main__':
    np.set_printoptions(precision=2, suppress=True)
    library = pd.read_csv('data/Mainland Odor Cabinet with CIDs.csv')
    weights = [('$/mol', 'mean', 1),
               ('MW', 'sum', 2),
               ('D g/ml', 'mean', -3)]
    optimizer = OdorantSetOptimizer(library, 25, weights, n_gen=25)
    pop, stats, hof, logbook = optimizer.run()

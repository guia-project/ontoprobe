from textx import metamodel_from_str, TextXSyntaxError
from rdflib import Graph
from rdflib.term import Literal
from rdflib.query import ResultException
from tabulate import tabulate
import math
import jmespath
import json
import os

def probe_file(ontology_uri_base: str, plantuml_file_path: str, ontology_file_path: str) -> dict:
    """
    Probes and validates an OWL ontology against a PlantUML model.

    This function performs a validation check between a PlantUML model representing
    an ontology and an actual OWL ontology file. It parses the PlantUML model,
    generates SPARQL queries to check for the existence and usage of classes,
    fields (datatype properties), and relationships (object and inheritance properties)
    defined in the PlantUML model within the provided OWL ontology.

    Raises:
        ValueError: If the provided `uri` is not a string or is empty.
        FileNotFoundError: If either `plantuml_file_path` or `ontology_file_path` does not exist.
        TextXSyntaxError: If the PlantUML file has syntax errors according to the grammar defined
                          in 'ontoProbe/metamodel.tx'.
        Exception: If any other unexpected error occurs during the validation process,
                   such as issues parsing files or executing SPARQL queries.
    """

    if not isinstance(ontology_uri_base, str) or not ontology_uri_base:
        raise ValueError("URI Base must be a non-empty string.")
    if not os.path.exists(plantuml_file_path):
        raise FileNotFoundError(f"PlantUML file not found: {plantuml_file_path}")
    if not os.path.exists(ontology_file_path):
        raise FileNotFoundError(f"Ontology file not found: {ontology_file_path}")
    
    plantuml_text = ""
    with open(plantuml_file_path, "r") as plantuml_file:
        plantuml_text = plantuml_file.read()

    ontology_text = ""
    with open(ontology_file_path, "r") as ontology_file:
        ontology_text = ontology_file.read()

    return probe_string(ontology_uri_base, plantuml_text, ontology_text)


def probe_string(ontology_uri_base: str, plantuml_text: str, ontology_text: str):

    if not isinstance(ontology_uri_base, str) or not ontology_uri_base:
        raise ValueError("URI Base must be a non-empty string.")
    if not isinstance(plantuml_text, str) or not ontology_uri_base:
        raise ValueError("PlantUml must be a non-empty string.")
    if not isinstance(ontology_uri_base, str) or not ontology_uri_base:
        raise ValueError("Ontology must be a non-empty string.")
    
    graph = Graph()
    graph.parse(data=ontology_text, format="turtle", encoding="utf-8")
    
    queries = _generate_queries(ontology_uri_base, plantuml_text)
    query_results = _run_sparql_queries(queries, graph)
    # analysis = _analyze_query_results(query_results)
    summary = summary_tables(query_results)

    return {
        "results": query_results,
        "summary": summary
    }

def _generate_queries(uri: str, plantuml_text: str) -> dict:
    """
    Generates SPARQL ASK and SELECT queries from a PlantUML model file.

    This function parses a PlantUML file describing an ontology model and generates
    a structured dictionary of SPARQL queries. The queries are designed to validate
    the existence and, for some elements, the 'usage' (a custom metric) of classes,
    fields, and relationships defined in the PlantUML model within an OWL ontology.

    Raises:
        TextXSyntaxError: If the PlantUML model file contains syntax errors based on 'ontoProbe/metamodel.tx' grammar.
        FileNotFoundError: If the PlantUML model file is not found at the specified path.
    """

    model = _get_model_from_str(plantuml_text)

    queries = {}
    for element in model.elements:
        match element.__class__.__name__:
            case "Class":
                queries[element.name] = _handle_class_element(uri, element)
            case "AssociationRelationship":
                if element.origin not in queries:
                    queries[element.origin] = {"relationships": {}}
                queries[element.origin]["relationships"][element.name] = _handle_association_relationship_element(uri, element)
            case "InheritanceRelationship":
                if element.origin not in queries:
                    queries[element.origin] = {"relationships": {}}
                queries[element.origin]["relationships"][f"inherits{element.target}"] = _handle_inheritance_relationship_element(uri, element)

    return queries

def _get_model_from_str(plantuml_text):
    metamodel = metamodel_from_str(
        """
        Plant:
            '@startuml'
            elements*=Element
            '@enduml'
        ;

        Element:
            Class | Relationship
        ;

        Class:
            ('abstract')? 'class' name=ID '{'
                fields*=ID
            '}'
        ;

        Relationship:
            AssociationRelationship | InheritanceRelationship
        ;

        AssociationRelationship:
            origin=ID '-->' target=ID ':' name=ID
        ;

        InheritanceRelationship:
            origin=ID '--|>' target=ID
        ;
        """
    )
    
    return metamodel.model_from_str(plantuml_text)


def _handle_class_element(uri, element):
    """
    Handles a PlantUML 'Class' element to generate relevant SPARQL queries.

    This function creates the query structure for a given PlantUML Class element,
    including queries for class existence and for each field's existence and usage.
    """
    return {
        "queries": {
            "existence": {
                "type": "ASK",
                "query": _generate_exist_class_sparql_query(uri, element.name)
            },
            "presence": {
                "type": "SELECT",
                "query": _generate_class_presence_sparql_query(uri, element.name)
            }
        },
        "fields": {
            field: {
                "queries": {
                    "existence": {
                        "type": "ASK",
                        "query": _generate_exist_field_sparql_query(
                            uri, field, element.name
                        )
                    },
                    "usage": {
                        "type": "SELECT",
                        "query": _generate_usage_sparql_query(
                            uri, element.name, field
                        )
                    },
                    "presence_per_instance": {
                        "type": "SELECT",
                        "query": _generate_presence_per_instance_sparql_query(
                            uri, element.name, field
                        )
                    }
                }
            } for field in element.fields
        },
        "relationships": {}
    }

def _handle_association_relationship_element(uri, element):
    """
    Handles a PlantUML 'AssociationRelationship' element to generate SPARQL queries.

    Generates SPARQL queries to check for the existence and usage of an association
    relationship (ObjectProperty) defined in the PlantUML model.
    """
    return {
        "type": "Association",
        "origin": element.origin,
        "target": element.target,
        "queries": {
            "existence": {
                "type": "ASK",
                "query": _generate_exist_association_relationship_sparql_query(
                    uri, element.name, element.origin, element.target
                )
            },
            "usage": {
                "type": "SELECT",
                "query": _generate_usage_sparql_query(
                    uri, element.origin, element.name
                )
            },
            "presence_per_instance": {
                "type": "SELECT",
                "query": _generate_presence_per_instance_sparql_query(
                    uri, element.origin, element.name
                )
            }
        }
    }

def _handle_inheritance_relationship_element(uri, element):
    """
    Handles a PlantUML 'InheritanceRelationship' element to generate SPARQL queries.

    Generates a SPARQL query to check for the existence of an inheritance relationship
    (subClassOf) defined in the PlantUML model.
    """
    return {
        "type": "Inheritance",
        "origin": element.origin,
        "target": element.target,
        "queries": {
            "existence": {
                "type": "ASK",
                "query": _generate_exist_inheritance_relationship_sparql_query(
                    uri, element.origin, element.target
                )
            }
        }
    }

def _generate_exist_class_sparql_query(uri: str, class_name: str) -> str:
    return f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>

    ASK {{
        <{uri}{class_name}> rdf:type owl:Class .
    }}
    """


def _generate_exist_field_sparql_query(uri: str, field: str, class_name: str) -> str:
    return f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>

    ASK {{
        <{uri}{class_name}_{field}> rdf:type owl:DatatypeProperty ;
        rdfs:domain <{uri}{class_name}> .
    }}
    """


def _generate_exist_association_relationship_sparql_query(
        uri: str, relationship_name: str,
        relationship_origin: str, relationship_target: str
    ) -> str:
    return f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>

    ASK {{
        <{uri}{relationship_origin}_{relationship_name}> rdf:type owl:ObjectProperty ;
        rdfs:domain <{uri}{relationship_origin}> ;
        rdfs:range <{uri}{relationship_target}> .
    }}
    """


def _generate_exist_inheritance_relationship_sparql_query(
        uri: str, relationship_origin: str, relationship_target: str
    ) -> str:
    return f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    ASK {{
        <{uri}{relationship_origin}> rdfs:subClassOf <{uri}{relationship_target}> .
    }}
    """

def _generate_usage_sparql_query(
        uri: str, class_domain: str, relationship_name: str
    ) -> str:

    return f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>

    SELECT (
        (
            (COUNT(DISTINCT ?subject)) / count(DISTINCT ?subject2)
        ) AS ?usage
    )
    WHERE {{
        OPTIONAL {{ 
            ?subject a <{uri}{class_domain}> .
            ?subject <{uri}{class_domain}_{relationship_name}> ?value .
        }}
        ?subject2 a <{uri}{class_domain}> .
    }}
    """

def _generate_presence_per_instance_sparql_query(
    uri: str, class_domain: str, relationship_name: str
) -> str:
    
    return f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>

    SELECT ?instance (COUNT(?value) AS ?presence)
    WHERE {{
        ?instance a <{uri}{class_domain}> .
        OPTIONAL {{ 
            ?instance <{uri}{class_domain}_{relationship_name}> ?value .
        }}
    }} GROUP BY ?instance
    """

def _generate_class_presence_sparql_query(
    uri: str, class_domain: str
) -> str:
    
    return f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>

    SELECT (COUNT(?instance) AS ?presence)
    WHERE {{
        ?instance a <{uri}{class_domain}> .
    }}
    """

def _run_sparql_queries(queries: dict, graph) -> dict:

    for class_name, class_data in queries.items():
        for query_name, query_data in class_data["queries"].items():
            result = None
            match query_data["type"]:
                case "ASK": result = _execute_ask_query(graph, query_data["query"])
                case "SELECT": result = _execute_select_query(graph, query_data["query"])
            queries[class_name]["queries"][query_name]["result"] = result

        if "fields" in class_data:
            for field_name, field_data in class_data["fields"].items():
                for query_name, query_data in field_data["queries"].items():
                    result = None
                    match query_data["type"]:
                        case "ASK": result = _execute_ask_query(graph, query_data["query"])
                        case "SELECT": result = _execute_select_query(graph, query_data["query"])
                    queries[class_name]["fields"][field_name]["queries"][query_name]["result"] = result

        if "relationships" in class_data:
            for relationship_name, relationship_data in class_data["relationships"].items():
                for query_name, query_data in relationship_data["queries"].items():
                    result = None
                    match query_data["type"]:
                        case "ASK": result = _execute_ask_query(graph, query_data["query"])
                        case "SELECT": result = _execute_select_query(graph, query_data["query"])
                    queries[class_name]["relationships"][relationship_name]["queries"][query_name]["result"] = result

    return queries


def _execute_ask_query(graph: Graph, query_string: str) -> str:
    
    if query_string is not None:
        try:
            query_result = graph.query(query_string)
            if bool(query_result):
                return "Success"
            else:
                return "Fail"
        except ResultException as e:
            return f"Error: SPARQL Query Error - {e}"
        except Exception as e:
            return f"Error: {e}"
    else:
        return "Error: No query defined"

def _execute_select_query(graph: Graph, query_string: str) -> list[dict] | str:
    
    if query_string is not None:
        try:
            query_result = graph.query(query_string)
            results_list = []
            if query_result:
                for row in query_result:
                    row_dict = {}
                    for var, value in zip(query_result.vars, row):
                        if isinstance(value, Literal):
                            row_dict[str(var)] = str(value.value)
                        else:
                            row_dict[str(var)] = value
                    results_list.append(row_dict)
                return results_list
            else:
                return "No results" 
        except ResultException as e:
            return f"Error: SPARQL Query Error - {e}"
        except Exception as e:
            return f"Error: {e}"
    else:
        return "Error: No query defined"


def _analyze_query_results(queries : dict) -> dict:

    for class_name, class_data in queries.items():
        class_data["calculations"] = {}
        class_data["calculations"]["fields_total"] = len(class_data["fields"])
        class_data["calculations"]["field_existence_fails"] = []

        for field_name, field_value in class_data["fields"].items():
            field_value["calculations"] = {}
            for query_name, query_value in field_value["queries"].items():
                match query_name:
                    case "existence":
                        if query_value["result"] == 'Fail':
                            class_data["calculations"]["field_existence_fails"].append(field_name)
                    case "presence_per_instance":
                        presence_per_instance = list(map(lambda e: int(e["presence"]), query_value["result"]))
                        presence_per_instance_len = len(presence_per_instance)
                        if presence_per_instance_len > 0:
                            presence_mean = sum(presence_per_instance) / presence_per_instance_len
                            presence_standard_deviation = math.sqrt(
                                sum(
                                    map(lambda x: (x - presence_mean) ** 2, presence_per_instance)
                                ) / presence_per_instance_len
                            )
                        else:
                            presence_mean = 0
                            presence_standard_deviation = 0
                        field_value["calculations"]["presence_mean"] = presence_mean
                        field_value["calculations"]["presence_standard_deviation"] = presence_standard_deviation

        class_data["calculations"]["relationship_total"] = len(class_data["relationships"])
        class_data["calculations"]["relationship_existence_fails"] = []
        for rel_name, rel_value in class_data["relationships"].items():
            rel_value["calculations"] = {}
            for query_name, query_value in rel_value["queries"].items():
                match query_name:
                    case "existence":
                        if query_value["result"] == 'Fail':
                            class_data["calculations"]["relationship_existence_fails"].append(rel_name)
                    case "presence_per_instance":
                        presence_per_instance = list(map(lambda e: int(e["presence"]), query_value["result"]))
                        presence_per_instance_len = len(presence_per_instance)
                        if presence_per_instance_len > 0:
                            presence_mean = sum(presence_per_instance) / presence_per_instance_len
                            presence_standard_deviation = math.sqrt(
                                sum(
                                    map(lambda x: (x - presence_mean) ** 2, presence_per_instance)
                                ) / presence_per_instance_len
                            )
                        else:
                            presence_mean = 0
                            presence_standard_deviation = 0
                        rel_value["calculations"]["presence_mean"] = presence_mean
                        rel_value["calculations"]["presence_standard_deviation"] = presence_standard_deviation

def summary_tables(data):
    """Print a summary of the ontology validation results in resizable tables."""

    print(f"\n{'=' * 80}")
    print(f"ONTOLOGY SUMMARY TEST RESULTS")
    print(f"{'=' * 80}")

    all_field_data_for_table = []

    for class_name, class_value in data.items():
        class_existence_result = class_value["queries"]["existence"]["result"] if "queries" in class_value and "existence" in class_value["queries"] else "N/A"
        is_first_field = True

        if "fields" in class_value and class_value["fields"]:
            for field_name, field_value in class_value["fields"].items():

                if ("existence" in field_value["queries"]):
                    existence_result = field_value["queries"]["existence"]["result"]
                else:
                    existence_result = "N/A"
                
                if ("usage" in field_value["queries"] and field_value["queries"]["usage"]["result"]):
                    usage_result = "{:.3f}".format(float(field_value["queries"]["usage"]["result"][0]["usage"]))
                else:
                    usage_result = "N/A"

                if ("calculations" in field_value):
                    if ("presence_mean" in field_value["calculations"]):
                        presence_mean = "{:.3f}".format(float(field_value["calculations"]["presence_mean"]))
                    else: 
                        presence_mean = "N/A"
                    if ("presence_standard_deviation" in field_value["calculations"]):
                        presence_std_dev = "{:.3f}".format(float(field_value["calculations"]["presence_standard_deviation"]))
                    else:
                        presence_std_dev = "N/A"
                else:
                    presence_mean = "N/A"
                    presence_std_dev = "N/A"

                class_display_name = class_name if is_first_field else ""
                class_existence_display = class_existence_result if is_first_field else "" 

                all_field_data_for_table.append([
                    class_display_name,
                    class_existence_display, # Class Existence Column
                    field_name,
                    existence_result,
                    usage_result,
                    presence_mean,
                    presence_std_dev
                ])
                is_first_field = False
        else:
            all_field_data_for_table.append([class_name, class_existence_result, "No fields", "", "", "", ""]) # Class with no fields

        if "relationships" in class_value and class_value["relationships"]:
            for rel_name, rel_value in class_value["relationships"].items():

                if ("existence" in rel_value["queries"]):
                    existence_result = rel_value["queries"]["existence"]["result"]
                else:
                    existence_result = "N/A"
                
                if ("usage" in rel_value["queries"] and rel_value["queries"]["usage"]["result"]):
                    usage_result = "{:.3f}".format(float(rel_value["queries"]["usage"]["result"][0]["usage"]))
                else:
                    usage_result = "N/A"

                if ("calculations" in rel_value):
                    if ("presence_mean" in rel_value["calculations"]):
                        presence_mean = "{:.3f}".format(float(rel_value["calculations"]["presence_mean"]))
                    else: 
                        presence_mean = "N/A"
                    if ("presence_standard_deviation" in rel_value["calculations"]):
                        presence_std_dev = "{:.3f}".format(float(rel_value["calculations"]["presence_standard_deviation"]))
                    else:
                        presence_std_dev = "N/A"
                else:
                    presence_mean = "N/A"
                    presence_std_dev = "N/A"

                class_display_name = class_name if is_first_field else ""
                class_existence_display = class_existence_result if is_first_field else "" # Display class existence only on first row

                all_field_data_for_table.append([
                    class_display_name,
                    class_existence_display, # Class Existence Column
                    field_name,
                    existence_result,
                    usage_result,
                    presence_mean,
                    presence_std_dev
                ])
                is_first_field = False
        else:
            all_field_data_for_table.append([class_name, class_existence_result, "No fields", "", "", "", ""]) # Class with no fields

    headers = ["Class", "Class Existence", "Element Name", "Existence", "Usage", "Presence Mean", "Presence StdDev"]
    table = tabulate(all_field_data_for_table, headers=headers, tablefmt="grid")
    print(table)
    print(f"{'-' * 80}")

    

def summary_class_table(data):
    """Print a table summarizing class-level validation results."""
    class_data_for_table = []
    for class_name, class_value in data.items():
        class_existence_result = "N/A"
        class_presence_result = "N/A"

        if "queries" in class_value:
            if "existence" in class_value["queries"]:
                class_existence_result = class_value["queries"]["existence"]["result"]
            if "presence" in class_value["queries"] and class_value["queries"]["presence"]["result"]:
                class_presence_result = class_value["queries"]["presence"]["result"][0]["presence"]
            
        class_data_for_table.append([class_name, class_existence_result, class_presence_result])

    headers = ["Class", "Class Existence", "Class Presence"]
    table = tabulate(class_data_for_table, headers=headers, tablefmt="grid")
    return table

def summary_fields_table(data):
    """Print a table summarizing field-level validation results for each class using provided logic."""
    all_field_data_for_table = []
    for class_name, class_value in data.items():
        if "fields" in class_value and class_value["fields"]:
            is_first_field = True
            for field_name, field_value in class_value["fields"].items():

                if "existence" in field_value["queries"]:
                    existence_result = field_value["queries"]["existence"]["result"]
                else:
                    existence_result = "N/A"

                if "usage" in field_value["queries"] and field_value["queries"]["usage"]["result"]:
                    usage_result = "{:.3f}".format(float(field_value["queries"]["usage"]["result"][0]["usage"]))
                else:
                    usage_result = "N/A"

                if "calculations" in field_value:
                    if "presence_mean" in field_value["calculations"]:
                        presence_mean = "{:.3f}".format(float(field_value["calculations"]["presence_mean"]))
                    else:
                        presence_mean = "N/A"
                    if "presence_standard_deviation" in field_value["calculations"]:
                        presence_std_dev = "{:.3f}".format(float(field_value["calculations"]["presence_standard_deviation"]))
                    else:
                        presence_std_dev = "N/A"
                else:
                    presence_mean = "N/A"
                    presence_std_dev = "N/A"

                class_display_name = class_name if is_first_field else ""

                all_field_data_for_table.append([
                    class_display_name,
                    field_name,
                    existence_result,
                    usage_result,
                    presence_mean,
                    presence_std_dev
                ])
                is_first_field = False
        else:
            all_field_data_for_table.append([class_name, "No fields", "", "", "", ""])

    headers = ["Class", "Field Name", "Existence", "Usage", "Presence Mean", "Presence StdDev"]
    table = tabulate(all_field_data_for_table, headers=headers, tablefmt="grid")
    return table

def summary_relationships_table(data):
    """Print a table summarizing relationship-level validation results for each class using provided logic."""
    all_relationship_data_for_table = []
    for class_name, class_value in data.items():
        if "relationships" in class_value and class_value["relationships"]:
            is_first_relationship = True
            for rel_name, rel_value in class_value["relationships"].items():
                rel_type = rel_value["type"]

                if "existence" in rel_value["queries"]:
                    existence_result = rel_value["queries"]["existence"]["result"]
                else:
                    existence_result = "N/A"

                if "usage" in rel_value["queries"] and rel_value["queries"]["usage"]["result"]:
                    usage_result = "{:.3f}".format(float(rel_value["queries"]["usage"]["result"][0]["usage"]))
                else:
                    usage_result = "N/A"

                if "calculations" in rel_value:
                    if "presence_mean" in rel_value["calculations"]:
                        presence_mean = "{:.3f}".format(float(rel_value["calculations"]["presence_mean"]))
                    else:
                        presence_mean = "N/A"
                    if "presence_standard_deviation" in rel_value["calculations"]:
                        presence_std_dev = "{:.3f}".format(float(rel_value["calculations"]["presence_standard_deviation"]))
                    else:
                        presence_std_dev = "N/A"
                else:
                    presence_mean = "N/A"
                    presence_std_dev = "N/A"

                class_display_name = class_name if is_first_relationship else ""
                target = rel_value.get("target", "N/A")

                all_relationship_data_for_table.append([
                    class_display_name,
                    rel_name,
                    rel_type,
                    target,
                    existence_result,
                    usage_result,
                    presence_mean,
                    presence_std_dev
                ])
                is_first_relationship = False
        else:
            all_relationship_data_for_table.append([class_name, "No relationships", "", "", "", "", "", ""])

    headers = ["Class", "Relationship Name", "Relationship Type", "Target", "Existence", "Usage", "Presence Mean", "Presence StdDev"]
    table = tabulate(all_relationship_data_for_table, headers=headers, tablefmt="grid")
    return table


def summary_tables(data):
    """Print a summary of the ontology validation results in separate resizable tables."""

    output_string = f"""
{'=' * 80}
                        ONTOLOGY SUMMARY TEST RESULTS
{'=' * 80}

{'-' * 80}
                                Class Summary
{'-' * 80}

{summary_class_table(data)}

{'-' * 80}
                                Field Summary
{'-' * 80}

{summary_fields_table(data)}

{'-' * 80}
                            Relationship Summary
{'-' * 80}

{summary_relationships_table(data)}
"""

    print(output_string)
    return output_string

if __name__ == '__main__':
    result = probe_file("http://example.org/ontology/", "model.puml", "test-ont2.ttl")
    # with open("model.puml", "r") as f1:
    #     with open("test-ont.ttl", "r") as f2:
    #         result = probe_string("http://example.org/ontology/", f1.read(), f2.read())

    #print(result)

    with open("output.json", 'w') as outfile:
        json.dump(result, outfile, indent=2)

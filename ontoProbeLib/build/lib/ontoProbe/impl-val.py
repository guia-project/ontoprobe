from textx import metamodel_from_file, TextXSyntaxError
from rdflib import Graph
from rdflib.term import Literal
from rdflib.query import ResultException
import jmespath
import json
import os

def probe(ontology_uri_base: str, plantuml_file_path: str, ontology_file_path: str) -> dict:
    """
    Probes and validates an OWL ontology against a PlantUML model.

    This function performs a validation check between a PlantUML model representing
    an ontology and an actual OWL ontology file. It parses the PlantUML model,
    generates SPARQL queries to check for the existence and usage of classes,
    fields (datatype properties), and relationships (object and inheritance properties)
    defined in the PlantUML model within the provided OWL ontology.

    Args:
        uri (str): The base URI for ontology concepts. This URI is prepended to class,
                   field, and relationship names to construct URIs used in SPARQL queries
                   (e.g., "http://example.org/ontology/"). Must be a non-empty string.
        plantuml_file_path (str): The file path to the PlantUML file (e.g., "model.puml")
                                  that describes the ontology model. This file is parsed
                                  to extract ontology elements.
        ontology_file_path (str): The file path to the OWL ontology file in Turtle (.ttl) format
                                   (e.g., "ontology.ttl"). This ontology is queried to validate
                                   against the PlantUML model.

    Returns:
        dict: A dictionary containing the validation summary and detailed results.
              The dictionary has the following structure:
              {
                  'summary': str,  # Human-readable summary of the validation results.
                  'details': {
                      'results': dict, # Raw results of SPARQL query execution.
                      'analysis': dict # Analyzed validation results, including metrics and failures.
                  }
              }

    Raises:
        ValueError: If the provided `uri` is not a string or is empty.
        FileNotFoundError: If either `plantuml_file_path` or `ontology_file_path` does not exist.
        TextXSyntaxError: If the PlantUML file has syntax errors according to the grammar defined
                          in 'ontoProbe/metamodel.tx'.
        Exception: If any other unexpected error occurs during the validation process,
                   such as issues parsing files or executing SPARQL queries.
    """
    if not isinstance(ontology_uri_base, str) or not ontology_uri_base:
        raise ValueError("URI must be a non-empty string.")
    if not os.path.exists(plantuml_file_path):
        raise FileNotFoundError(f"PlantUML file not found: {plantuml_file_path}")
    if not os.path.exists(ontology_file_path):
        raise FileNotFoundError(f"Ontology file not found: {ontology_file_path}")

    queries = _generate_queries(ontology_uri_base, plantuml_file_path)
    query_results = _run_sparql_queries(queries, ontology_file_path)
    analysis = _analyze_query_results(query_results)
    summary = _generate_summary_report(analysis)

    return {
        "summary": summary,
        "details": {
            "results": query_results,
            "analysis": analysis,
        }
    }


def _generate_queries(uri: str, plantuml_file_path: str) -> dict:
    """
    Generates SPARQL ASK and SELECT queries from a PlantUML model file.

    This function parses a PlantUML file describing an ontology model and generates
    a structured dictionary of SPARQL queries. The queries are designed to validate
    the existence and, for some elements, the 'usage' (a custom metric) of classes,
    fields, and relationships defined in the PlantUML model within an OWL ontology.

    The structure of the returned dictionary is designed to be easily processed in
    subsequent steps of the validation process. It organizes queries by class and then
    by element type (queries for the class itself, its fields, and its relationships).

    Args:
        uri (str): The base URI for ontology concepts, used to construct URIs in SPARQL queries.
        plantuml_file_path (str): Path to the PlantUML file defining the ontology model.

    Returns:
        dict: A nested dictionary representing the generated SPARQL queries. The structure is:
              {
                  "ClassName": {
                      "queries": { # Queries related to the class itself
                          "existence": {"type": "ASK", "query": "SPARQL ASK query string"},
                      },
                      "fields": { # Queries for fields (datatype properties) of the class
                          "fieldName": {
                              "queries": {
                                  "existence": {"type": "ASK", "query": "SPARQL ASK query string"},
                                  "usage": {"type": "SELECT", "query": "SPARQL SELECT query string"},
                              }
                          }
                      },
                      "relationships": { # Queries for relationships (object & inheritance properties)
                          "relationshipName": { # Could be association or inheritance relationship name
                              "type": "Association" or "Inheritance",
                              "origin": "OriginClassName",
                              "target": "TargetClassName",
                              "queries": {
                                  "existence": {"type": "ASK", "query": "SPARQL ASK query string"},
                                  "usage": {"type": "SELECT", "query": "SPARQL SELECT query string"} (only for Association),
                              }
                          }
                      }
                  },
                  ... (more classes and their queries)
              }

    Raises:
        TextXSyntaxError: If the PlantUML model file contains syntax errors based on 'ontoProbe/metamodel.tx' grammar.
        FileNotFoundError: If the PlantUML model file is not found at the specified path.
    """
    metamodel = metamodel_from_file("ontoProbe/metamodel.tx")
    model = metamodel.model_from_file(plantuml_file_path)

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


def _handle_class_element(uri, element):
    """
    Handles a PlantUML 'Class' element to generate relevant SPARQL queries.

    This function creates the query structure for a given PlantUML Class element,
    including queries for class existence and for each field's existence and usage.

    Args:
        uri (str): The base URI for ontology concepts.
        element: The PlantUML 'Class' element object parsed by textX.

    Returns:
        dict: A dictionary containing query definitions for the class and its fields.
              Structure:
              {
                  "queries": { "existence": { ... } }, # Class existence query
                  "fields": { # Field-specific queries
                      "fieldName": { "queries": { "existence": { ... }, "usage": { ... } } },
                      ...
                  },
                  "relationships": {} # Placeholder for relationships, populated later
              }
    """
    return {
        "queries": {
            "existence": {
                "type": "ASK",
                "query": _generate_exist_class_sparql_query(uri, element.name)
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

    Args:
        uri (str): The base URI for ontology concepts.
        element: The PlantUML 'AssociationRelationship' element object parsed by textX.

    Returns:
        dict: A dictionary containing query definitions for the association relationship.
              Structure:
              {
                  "type": "Association",
                  "origin": "OriginClassName",
                  "target": "TargetClassName",
                  "queries": {
                      "existence": { ... }, # Relationship existence query
                      "usage": { ... }  # Relationship usage query
                  }
              }
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
            }
        }
    }

def _handle_inheritance_relationship_element(uri, element):
    """
    Handles a PlantUML 'InheritanceRelationship' element to generate SPARQL queries.

    Generates a SPARQL query to check for the existence of an inheritance relationship
    (subClassOf) defined in the PlantUML model.

    Args:
        uri (str): The base URI for ontology concepts.
        element: The PlantUML 'InheritanceRelationship' element object parsed by textX.

    Returns:
        dict: A dictionary containing query definitions for the inheritance relationship.
              Structure:
              {
                  "type": "Inheritance",
                  "origin": "OriginClassName",
                  "target": "TargetClassName",
                  "queries": {
                      "existence": { ... } # Inheritance existence query
                  }
              }
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
    """
    Generates a SPARQL ASK query to check if an OWL Class exists in the ontology.

    Args:
        uri (str): The base URI for ontology concepts.
        class_name (str): The name of the class to check for existence.

    Returns:
        str: SPARQL ASK query string.
    """
    return f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>

    ASK {{
        <{uri}{class_name}> rdf:type owl:Class .
    }}
    """


def _generate_exist_field_sparql_query(uri: str, field: str, class_name: str) -> str:
    """
    Generates a SPARQL ASK query to check if an OWL DatatypeProperty (field) exists.

    This query verifies the existence of a datatype property and confirms that its
    domain is set to the specified class.

    Args:
        uri (str): The base URI for ontology concepts.
        field (str): The name of the field (datatype property) to check.
        class_name (str): The name of the class expected to be the domain of the field.

    Returns:
        str: SPARQL ASK query string.
    """
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
    """
    Generates a SPARQL ASK query to check if an OWL ObjectProperty (association relationship) exists.

    This query verifies the existence of an object property and confirms that its
    domain and range are correctly set to the specified origin and target classes.

    Args:
        uri (str): The base URI for ontology concepts.
        relationship_name (str): The name of the association relationship (object property).
        relationship_origin (str): The name of the origin class (domain of the object property).
        relationship_target (str): The name of the target class (range of the object property).

    Returns:
        str: SPARQL ASK query string.
    """
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
    """
    Generates a SPARQL ASK query to check if an OWL inheritance (subClassOf) relationship exists.

    This query verifies if the `relationship_origin` class is defined as a subclass of
    the `relationship_target` class.

    Args:
        uri (str): The base URI for ontology concepts.
        relationship_origin (str): The name of the origin class (subclass).
        relationship_target (str): The name of the target class (superclass).

    Returns:
        str: SPARQL ASK query string.
    """
    return f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    ASK {{
        <{uri}{relationship_origin}> rdfs:subClassOf <{uri}{relationship_target}> .
    }}
    """

def _generate_usage_sparql_query(
        uri: str, class_domain: str, relationship_name: str
    ) -> str:
    """
    Generates a SPARQL SELECT query to calculate the 'usage' metric for a property.

    Usage is calculated as the ratio of the count of distinct subjects (instances of
    `class_domain`) that have a value for the given `relationship_name` property,
    to the count of all distinct values for that property across all subjects of `class_domain`.
    This metric provides a simple measure of how consistently a property is used across
    instances of its domain class.

    Args:
        uri (str): The base URI for ontology concepts.
        class_domain (str): The name of the domain class for the property.
        relationship_name (str): The name of the property (field or association relationship).

    Returns:
        str: SPARQL SELECT query string that calculates the usage metric.
    """

    # ((count(distinct ?subject) / count(?distinc value)) as ?usage) 
    # -> ((count(?value) / count(distinct ?subject)) as ?usage)
    # return f"""
    # PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    # PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    # PREFIX owl: <http://www.w3.org/2002/07/owl#>
    # 
    # SELECT ((count(?value) / count(distinct ?subject)) as ?usage) WHERE {{
    #     ?subject a <{uri}{class_domain}> .
    #     OPTIONAL {{ ?subject <{uri}{class_domain}_{relationship_name}> ?value .}}
    # }}
    # """

    return f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>

    SELECT ((SUM(IF(BOUND(?value), 1, 0)) * 1.0) / count(DISTINCT ?subject) AS ?usage)
    WHERE {{
        ?subject a <{uri}{class_domain}> .
        OPTIONAL {{ ?subject <{uri}{class_domain}_{relationship_name}> ?value .}}
    }}
    """




def _run_sparql_queries(queries: dict, ontology_file_path: str) -> dict:
    """
    Executes a dictionary of SPARQL queries against the specified ontology file.

    This function iterates through the provided dictionary of queries, executes each one
    against the ontology loaded from `ontology_file_path`, and updates the query dictionary
    with the execution results.

    Args:
        queries (dict): A dictionary of SPARQL queries, typically generated by `_generate_queries`.
                        See `_generate_queries` documentation for the expected structure.
        ontology_file_path (str): Path to the OWL ontology file in Turtle format (.ttl).

    Returns:
        dict: The input `queries` dictionary, updated in-place with the query results.
              Each query definition now includes a 'result' key containing the query outcome.
              For ASK queries, 'result' is "Success", "Fail", or an error string.
              For SELECT queries, 'result' is a list of dictionaries or an error string.

    Raises:
        FileNotFoundError: If the ontology file is not found.
        Exception: If any error occurs during ontology parsing or SPARQL query execution.
                   Specific exceptions like `QueryException` during query execution are caught
                   and their error messages are recorded in the results.
    """
    graph = Graph()
    try:
        graph.parse(ontology_file_path, format="turtle")
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Ontology file not found: {ontology_file_path}") from e
    except Exception as e:
        raise Exception(f"Error parsing ontology file: {ontology_file_path}. {e}") from e

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
    """
    Executes a SPARQL ASK query against an rdflib Graph and returns the result status.

    This function executes a SPARQL ASK query and handles potential errors during execution.

    Args:
        graph (Graph): The rdflib Graph to execute the query against.
        query_string (str): The SPARQL ASK query string.

    Returns:
        str: "Success" if the query returns true, "Fail" if false, or an "Error: ..." message
             if a `QueryException` occurs during query execution, or "Error: No query defined"
             if the query_string is None.
    """
    if query_string is not None:
        try:
            query_result = graph.query(query_string)
            return "Success" if query_result.askAnswer else "Fail"
        except ResultException as e:
            return f"Error: SPARQL Query Error - {e}"
        except Exception as e:
            return f"Error: {e}"
    else:
        return "Error: No query defined"

def _execute_select_query(graph: Graph, query_string: str) -> list[dict] | str:
    """
    Executes a SPARQL SELECT query against an rdflib Graph and returns results as a list of dictionaries.

    This function executes a SPARQL SELECT query, processes the results, and handles
    potential errors during query execution. It extracts Python values from rdflib Literal objects
    in the query results to make the output more Python-friendly.

    Args:
        graph (Graph): The rdflib Graph to execute the query against.
        query_string (str): The SPARQL SELECT query string.

    Returns:
        list[dict] | str: A list of dictionaries, where each dictionary represents a row in the result set
                           and keys are SPARQL variable names. Returns "No results" if the query
                           executes successfully but returns no bindings. Returns "Error: ..." if a
                           `QueryException` occurs during query execution, or "Error: No query defined"
                           if the query_string is None.
    """
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


def _analyze_query_results(queries: dict) -> dict:
    """
    Analyzes the SPARQL query results to provide a validation summary using jmespath with minimal Python code.
    """

    analysis = {}

    for class_name, class_data in queries.items():
        analysis[class_name] = {}

        # Class Query Analysis
        ## Existence
        analysis[class_name]["class_query_total"] = 1
        analysis[class_name]["class_query_fails"] = jmespath.search("queries.existence.result == 'Fail'", class_data) or 0

        # Field Query Analysis
        ## Existence
        analysis[class_name]["field_query_total"] = jmespath.search("length(fields)", class_data) or 0
        analysis[class_name]["field_query_fails"] = jmespath.search("length(fields.*.queries[?existence.result == 'Fail'])", class_data) or 0
        analysis[class_name]["failed_fields"] = jmespath.search("keys(fields)[*][?fields.\"^\".queries.existence.result == 'Fail']", class_data) or []

        ## Usage
        usage_results_fields = jmespath.search("fields.*.queries[].usage.result[].usage", class_data) or []
        field_names = list(class_data["fields"].keys()) if "fields" in class_data else []
        analysis[class_name].update({f"field_usage_{field_names[i]}": usage_results_fields[i] for i in range(len(field_names)) if usage_results_fields and usage_results_fields[i] is not None})

        # Relationship Query Analysis
        ## Existence
        analysis[class_name]["relationship_query_total"] = jmespath.search("length(relationships)", class_data) or 0
        analysis[class_name]["relationship_query_fails"] = jmespath.search("length(relationships.*.queries[?existence.result == 'Fail'])", class_data) or 0
        analysis[class_name]["failed_relationships"] = jmespath.search("keys(relationships)[*][?relationships.\"^\".queries.existence.result == 'Fail']", class_data) or []

        ## Usage
        usage_results_relationships = jmespath.search("relationships.*.queries[].usage.result[].usage", class_data) or []
        relationship_names = list(class_data["relationships"].keys()) if "relationships" in class_data else []
        analysis[class_name].update({f"relationship_usage_{relationship_names[i]}": usage_results_relationships[i] for i in range(len(relationship_names)) if usage_results_relationships and usage_results_relationships[i] is not None})

        # Overall Class Analysis
        analysis[class_name]["total_fails"] = (analysis[class_name]["class_query_fails"] + analysis[class_name]["field_query_fails"] + analysis[class_name]["relationship_query_fails"])
        analysis[class_name]["total_queries"] = (analysis[class_name]["class_query_total"] + analysis[class_name]["field_query_total"] + analysis[class_name]["relationship_query_total"])
        analysis[class_name]["quality"] = (1 - (analysis[class_name]["total_fails"] / analysis[class_name]["total_queries"])) if analysis[class_name]["total_queries"] > 0 else 1.0

    # Overall Summary Analysis
    analysis["overall_class_query_fails"] = jmespath.search("sum(values(@)[?class_query_total].class_query_fails)", analysis) or 0
    analysis["overall_field_query_fails"] = jmespath.search("sum(values(@)[?field_query_total].field_query_fails)", analysis) or 0
    analysis["overall_relationship_query_fails"] = jmespath.search("sum(values(@)[?relationship_query_total].relationship_query_fails)", analysis) or 0

    return analysis


def _generate_summary_report(analysis: dict) -> str:
    """
    Generates a summary report as a string, grouped by validation type (existence, usage).
    """

    summary = ""

    summary += "\n===================[ Validation Summary Report ]===================\n"

    total_quality = 0
    for class_name, class_analysis in analysis.items():
        if class_name not in ["overall_class_query_fails", "overall_field_query_fails", "overall_relationship_query_fails"]:
            summary += f"\n--- Class: {class_name} ---\n"
            summary += f"  Quality Score: {class_analysis['quality']:.2f}\n"
            summary += f"  Total Queries: {class_analysis['total_queries']}\n"
            summary += f"  Failing Queries: {class_analysis['total_fails']}\n"

            summary += "  --- Existence Validation ---\n"
            summary += f"    Class Existence Fails: {class_analysis['class_query_fails']}\n"
            summary += f"    Field Existence Fails: {class_analysis['field_query_fails']}\n"

            if 'failed_fields' in class_analysis and class_analysis['failed_fields']:
                summary += "      Failed Fields: " + ", ".join(class_analysis['failed_fields']) + "\n"
            summary += f"    Relationship Existence Fails: {class_analysis['relationship_query_fails']}\n"

            if 'failed_relationships' in class_analysis and class_analysis['failed_relationships']:
                failed_relationships_names = [name for name in class_analysis['failed_relationships']] # names are keys already
                summary += "      Failed Relationships: " + ", ".join(failed_relationships_names) + "\n"

            summary += "  --- Usage Validation ---\n"

            for key, value in class_analysis.items():
                if key.startswith("field_usage_"):
                    field_name = key.replace("field_usage_", "")
                    summary += f"    Field Usage ({field_name}): {value}\n"
                elif key.startswith("relationship_usage_"):
                    relationship_name = key.replace("relationship_usage_", "")
                    summary += f"    Relationship Usage ({relationship_name}): {value}\n"


            total_quality += class_analysis['quality']

    overall_quality = total_quality / (len(analysis) - 3) if (len(analysis) - 3) > 0 else 1.0
    summary += f"\n--- Overall Summary ---\n"
    summary += f"  Overall Quality Score: {overall_quality:.2f}\n"
    summary += f"  Total Class Query Fails: {analysis.get('overall_class_query_fails', 0)}\n"
    summary += f"  Total Field Query Fails: {analysis.get('overall_field_query_fails', 0)}\n"
    summary += f"  Total Relationship Query Fails: {analysis.get('overall_relationship_query_fails', 0)}\n"

    summary += "\n===================[ End Summary ]===================\n"
    return summary

if __name__ == '__main__':
    result = probe("http://example.org/ontology/", "model.puml", "test-ont.ttl")
    print(result["summary"])

    with open("output.json", 'w') as outfile:
        json.dump(result, outfile, indent=2)
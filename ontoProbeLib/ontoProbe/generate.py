from textx import metamodel_from_str, TextXSyntaxError

def generate(ontology_uri, model_file_path):
    """
    Generates the RDF Turtle string from a parsed PlantUML model.

    Args:
        ontology_uri (str): The base URI for the generated ontology.
        model: The parsed PlantUML model object from textX.

    Returns:
        str: The RDF ontology as a Turtle string.
    """

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

    model = metamodel.model_from_file(model_file_path)

    result = f"""
    @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    @prefix onto: <{ontology_uri}> .

    <{ontology_uri}> a owl:Ontology .

    """

    for element in model.elements:
        match element.__class__.__name__:
            case "Class":
                result += f"onto:{element.name} a owl:Class ." + "\n"
                for field in element.fields:
                    result += f"onto:{element.name}_{field} a owl:DatatypeProperty ;\n"
                    result += f"\t rdfs:domain onto:{element.name} ;\n"
                    result += f"\t rdfs:range xsd:string ." + "\n"
                result += "\n"
            case "AssociationRelationship":
                result += f"onto:{element.origin}_{element.name} a owl:ObjectProperty ;\n"
                result += f"\t rdfs:domain onto:{element.origin} ;\n"
                result += f"\t rdfs:range onto:{element.target} ." + "\n"
                result += "\n"
            case "InheritanceRelationship":
                result += f"onto:{element.origin} rdfs:subClassOf onto:{element.target} ." + "\n"
                result += "\n"
    return result

if __name__ == '__main__':
    res = generate("http://example.org/ontology/", "model.puml")
    print(res)
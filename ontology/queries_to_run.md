PREFIX ontolex: <http://www.w3.org/ns/lemon/ontolex#>

<!-- query 1 -->
<!-- every English term in the graph. -->
<!-- find me any node (?entry) that has a canonicalForm containing a writtenRep — put that written value into ?term — then keep only the ones where the language tag is English. -->

```sparql
SELECT ?term
WHERE {
  ?entry ontolex:canonicalForm [ ontolex:writtenRep ?term ] .
  FILTER(lang(?term) = "en")
}
```

<!-- query 2 -->

```sparql
SELECT ?spanishTerm
WHERE {
    # find an English entry whose written form is "asthma"
    ?enEntry ontolex:canonicalForm [ ontolex:writtenRep "asthma"@en ] ;
    # follow its sense to get the concept it references — store that in ?concept
             ontolex:sense [ ontolex:reference ?concept ] .

    # find a Spanish entry that references the exact same ?concept
    ?esEntry ontolex:sense [ ontolex:reference ?concept ] ;
    # get its written form — store in ?spanishTerm
             ontolex:canonicalForm [ ontolex:writtenRep ?spanishTerm ] .

    # keep only results where that string is tagged Spanish
    FILTER(lang(?spanishTerm) = "es")
}
```

<!-- look into VarTrans and Decomp of Ontolex -->
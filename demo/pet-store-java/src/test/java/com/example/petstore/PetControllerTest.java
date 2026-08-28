package com.example.petstore;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_EACH_TEST_METHOD)
class PetControllerTest {

    @Autowired
    private MockMvc mvc;

    @Test
    void listStartsEmpty() throws Exception {
        mvc.perform(get("/pets"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void createThenGetPet() throws Exception {
        mvc.perform(post("/pets")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"Mochi\",\"species\":\"cat\",\"price\":12.5}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.name").value("Mochi"))
                .andExpect(jsonPath("$.status").value("AVAILABLE"));

        mvc.perform(get("/pets/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.species").value("cat"));
    }

    @Test
    void createRejectsNegativePrice() throws Exception {
        mvc.perform(post("/pets")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"Nemo\",\"species\":\"fish\",\"price\":-1}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("price must not be negative"));
    }

    @Test
    void buyThenRejectSecondBuy() throws Exception {
        mvc.perform(post("/pets")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"Kiwi\",\"species\":\"bird\",\"price\":20}"))
                .andExpect(status().isOk());

        mvc.perform(post("/pets/1/buy"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("SOLD"));

        mvc.perform(post("/pets/1/buy"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error").value("pet already sold: 1"));
    }

    @Test
    void getMissingPet() throws Exception {
        mvc.perform(get("/pets/99"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("pet not found: 99"));
    }
}
